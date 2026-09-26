//! The thin layer between Zed and `logic.rs`. Finds a Python, fetches the server
//! from a GitHub release and hands Zed the command to run.

mod logic;

use std::fs;
use std::path::Path;

use logic::{
    choose_interpreter, executable_to_start, interpreter_candidates, is_bare_name, libs_dir,
    newest_server_dir, parse_probe, parse_settings, pick_asset, probe_env, probe_failure,
    project_root, server_dir_name, server_env, stale_server_dirs, workspace_configuration,
    Candidate, FetchError, Os, ProbeOutcome, Settings, INSTALL_MARKER, NOTICE_VAR, PROBE,
    PROBE_ARGS, REPO, SERVER_ARGS, SERVER_ID,
};
use zed_extension_api::settings::LspSettings;
use zed_extension_api::{self as zed, LanguageServerId, LanguageServerInstallationStatus, Result};

struct PytaExtension {
    // The server directory the last start used, relative to the work dir, so one
    // Zed session looks the release up once.
    server_dir: Option<String>,
    // Something the user should know about the last server lookup. The server
    // logs it at startup, since the extension has no log of its own.
    notice: Option<String>,
}

fn host_os() -> Os {
    match zed::current_platform().0 {
        zed::Os::Mac => Os::Mac,
        zed::Os::Linux => Os::Linux,
        zed::Os::Windows => Os::Windows,
    }
}

/// Runs the probe the way the server will run: with the same env, and with pyenv
/// pointed at the project so a shim resolves the same version in both places.
fn probe(python: &str, env: &[(String, String)]) -> ProbeOutcome {
    let mut command = zed::process::Command::new(python)
        .args(PROBE_ARGS)
        .arg(PROBE)
        .envs(env.iter().cloned());
    let output = match command.output() {
        Ok(output) => output,
        Err(error) => return ProbeOutcome::Failed(error),
    };
    if output.status != Some(0) {
        return ProbeOutcome::Failed(probe_failure(
            output.status,
            &String::from_utf8_lossy(&output.stderr),
        ));
    }
    match parse_probe(&String::from_utf8_lossy(&output.stdout)) {
        Ok(probed) => ProbeOutcome::Found(
            probed.version,
            executable_to_start(python, probed.executable.as_deref(), host_os()),
        ),
        Err(reason) => ProbeOutcome::Failed(reason),
    }
}

/// The absolute extension work dir. Zed passes it in PWD with forward slashes on
/// every OS, and the API crate sets the WASI cwd from that same variable at init,
/// so the cwd is only the fallback.
fn work_dir() -> Result<String> {
    match std::env::var("PWD") {
        Ok(pwd) if !pwd.trim().is_empty() => Ok(pwd),
        _ => std::env::current_dir()
            .map(|dir| dir.to_string_lossy().into_owned())
            .map_err(|error| format!("could not read the extension directory: {error}")),
    }
}

fn has_libs(server_dir: &str) -> bool {
    Path::new(server_dir).join("libs").is_dir()
}

/// A download that got all the way through the check at the end of `download`.
fn is_installed(server_dir: &str) -> bool {
    has_libs(server_dir) && Path::new(server_dir).join(INSTALL_MARKER).is_file()
}

/// The server directories in the work dir, only the ones a download finished in.
fn usable_server_dirs() -> Vec<String> {
    fs::read_dir(".")
        .map(|entries| {
            entries
                .filter_map(|entry| entry.ok())
                .map(|entry| entry.file_name().to_string_lossy().into_owned())
                .filter(|name| is_installed(name))
                .collect()
        })
        .unwrap_or_default()
}

fn all_server_dirs() -> Vec<String> {
    fs::read_dir(".")
        .map(|entries| {
            entries
                .filter_map(|entry| entry.ok())
                .filter(|entry| entry.path().is_dir())
                .map(|entry| entry.file_name().to_string_lossy().into_owned())
                .collect()
        })
        .unwrap_or_default()
}

impl PytaExtension {
    fn find_python(&self, settings: &Settings, worktree: &zed::Worktree) -> Result<String> {
        let root = worktree.root_path();
        let os = host_os();
        // Reading the root entry itself succeeds for a single UTF-8 file worktree
        // and fails for a directory, which is how Zed tells us which one this is.
        let project = project_root(&root, worktree.read_text_file("").is_ok());
        let shell_env = worktree.shell_env();
        let envs: Vec<Vec<(String, String)>> = project
            .pyenv_dirs
            .iter()
            .map(|dir| probe_env(shell_env.clone(), os, dir))
            .collect();
        let candidates = interpreter_candidates(settings, &project.venv_bases, os);
        choose_interpreter(&candidates, |candidate| {
            // A bare name is looked up here, because Zed would otherwise treat the
            // command as a path inside the extension directory.
            let python = match candidate {
                Candidate::OnPath(name) => worktree.which(name),
                Candidate::Configured(value) if is_bare_name(value) => worktree.which(value),
                Candidate::Configured(path) | Candidate::Venv(path) => Some(path.clone()),
            };
            let Some(python) = python else {
                return ProbeOutcome::Missing;
            };
            // A pyenv shim refuses a PYENV_DIR that is not a directory, so the
            // next entry, the parent, gets a turn before the candidate is given up.
            let mut outcome = ProbeOutcome::Missing;
            for env in &envs {
                outcome = probe(&python, env);
                if !matches!(outcome, ProbeOutcome::Failed(_)) {
                    break;
                }
            }
            outcome
        })
    }

    fn server_libs(&mut self, id: &LanguageServerId, settings: &Settings) -> Result<String> {
        if let Some(dir) = &settings.server_dir {
            // The notice is about the downloaded server, which stays cached and
            // may be used again once serverDir is removed, so it is kept.
            return Ok(dir.clone());
        }
        let work_dir = work_dir()?;
        // A restart in the same session reuses the directory, and the notice that
        // explained it the first time, since the reason has not changed.
        if let Some(server_dir) = &self.server_dir {
            if is_installed(server_dir) {
                return Ok(libs_dir(&work_dir, server_dir));
            }
        }
        zed::set_language_server_installation_status(
            id,
            &LanguageServerInstallationStatus::CheckingForUpdate,
        );
        let server_dir = match self.install_latest(id) {
            Ok(server_dir) => {
                self.notice = None;
                server_dir
            }
            // Offline, or the release is not there yet. An earlier download still works.
            Err(error) => {
                let existing = usable_server_dirs();
                match newest_server_dir(existing.iter().map(String::as_str)) {
                    Some(existing) => {
                        self.notice = Some(format!(
                            "{} Using the earlier download in {existing} for now.",
                            error.message()
                        ));
                        existing.to_string()
                    }
                    None => {
                        let message = error.message();
                        zed::set_language_server_installation_status(
                            id,
                            &LanguageServerInstallationStatus::Failed(message.clone()),
                        );
                        return Err(message);
                    }
                }
            }
        };
        zed::set_language_server_installation_status(id, &LanguageServerInstallationStatus::None);
        let libs = libs_dir(&work_dir, &server_dir);
        self.server_dir = Some(server_dir);
        Ok(libs)
    }

    /// Downloads the newest release into its own directory and returns that directory name.
    fn install_latest(&self, id: &LanguageServerId) -> std::result::Result<String, FetchError> {
        let release = zed::latest_github_release(
            REPO,
            zed::GithubReleaseOptions {
                require_assets: true,
                pre_release: false,
            },
        )
        .map_err(FetchError::Failed)?;
        let asset_name = pick_asset(release.assets.iter().map(|asset| asset.name.as_str()))
            .ok_or_else(|| FetchError::NoTarball {
                tag: release.version.clone(),
            })?;
        let asset = release
            .assets
            .iter()
            .find(|asset| asset.name == asset_name)
            .expect("the picked asset came from this list");
        let dir_name = server_dir_name(&release.version);
        if is_installed(&dir_name) {
            return Ok(dir_name);
        }
        zed::set_language_server_installation_status(
            id,
            &LanguageServerInstallationStatus::Downloading,
        );
        if let Err(error) = self.download(asset, &dir_name) {
            // A half written directory must never pass for a finished one, since the
            // fallback above would then start a server that isnt there.
            let _ = fs::remove_dir_all(&dir_name);
            return Err(FetchError::Failed(error));
        }
        for stale in stale_server_dirs(all_server_dirs().iter().map(String::as_str), &dir_name) {
            // Best effort, a leftover only costs disk space.
            let _ = fs::remove_dir_all(stale);
        }
        Ok(dir_name)
    }

    fn download(&self, asset: &zed::GithubReleaseAsset, dir_name: &str) -> Result<()> {
        let dir = Path::new(dir_name);
        // Whatever a broken earlier download left behind must not be mistaken for the real thing.
        if dir.exists() {
            fs::remove_dir_all(dir)
                .map_err(|error| format!("could not clear {dir_name}: {error}"))?;
        }
        zed::download_file(
            &asset.download_url,
            dir_name,
            zed::DownloadedFileType::GzipTar,
        )
        .map_err(|error| format!("downloading {} failed: {error}", asset.name))?;
        if !has_libs(dir_name) {
            return Err(format!("{} did not contain a libs directory", asset.name));
        }
        if !dir
            .join("libs")
            .join("pyta_lsp")
            .join("__init__.py")
            .is_file()
        {
            return Err(format!(
                "{} did not contain the pyta_lsp package",
                asset.name
            ));
        }
        fs::write(
            dir.join(INSTALL_MARKER),
            "written by the PythonTA Zed extension once the download was checked\n",
        )
        .map_err(|error| format!("could not mark {dir_name} as installed: {error}"))?;
        Ok(())
    }
}

impl zed::Extension for PytaExtension {
    fn new() -> Self {
        Self {
            server_dir: None,
            notice: None,
        }
    }

    fn language_server_command(
        &mut self,
        id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        let lsp = LspSettings::for_worktree(SERVER_ID, worktree).unwrap_or_default();
        let settings = parse_settings(lsp.settings.as_ref())?;
        let python = self.find_python(&settings, worktree)?;
        let libs = self.server_libs(id, &settings)?;
        let mut env = server_env(worktree.shell_env(), &libs, host_os());
        if let (Some(notice), None) = (&self.notice, &settings.server_dir) {
            env.push((NOTICE_VAR.to_string(), notice.clone()));
        }
        Ok(zed::Command {
            command: python,
            args: SERVER_ARGS.iter().map(|arg| arg.to_string()).collect(),
            env,
        })
    }

    fn language_server_initialization_options(
        &mut self,
        _id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Option<zed::serde_json::Value>> {
        Ok(LspSettings::for_worktree(SERVER_ID, worktree)
            .ok()
            .and_then(|lsp| lsp.initialization_options))
    }

    fn language_server_workspace_configuration(
        &mut self,
        _id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Option<zed::serde_json::Value>> {
        let options = LspSettings::for_worktree(SERVER_ID, worktree)
            .ok()
            .and_then(|lsp| lsp.initialization_options);
        Ok(Some(workspace_configuration(options)))
    }
}

zed::register_extension!(PytaExtension);
