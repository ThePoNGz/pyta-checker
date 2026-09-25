//! The thin layer between Zed and `logic.rs`. Finds a Python, fetches the server
//! from a GitHub release and hands Zed the command to run.

mod logic;

use std::fs;
use std::path::Path;

use logic::{
    check_version, interpreter_candidates, libs_dir, newest_server_dir, parse_probe,
    parse_settings, pick_asset, probe_failure, server_dir_name, server_env, stale_server_dirs,
    workspace_configuration, Candidate, FetchError, Os, PythonVersion, Settings, PROBE, PROBE_ARGS,
    REPO, SERVER_ARGS, SERVER_ID,
};
use zed_extension_api::settings::LspSettings;
use zed_extension_api::{self as zed, LanguageServerId, LanguageServerInstallationStatus, Result};

struct PytaExtension {
    // The server directory the last start used, relative to the work dir, so one
    // Zed session looks the release up once.
    server_dir: Option<String>,
}

fn host_os() -> Os {
    match zed::current_platform().0 {
        zed::Os::Mac => Os::Mac,
        zed::Os::Linux => Os::Linux,
        zed::Os::Windows => Os::Windows,
    }
}

fn probe(python: &str) -> Result<PythonVersion> {
    let output = zed::process::Command::new(python)
        .args(PROBE_ARGS)
        .arg(PROBE)
        .output()?;
    if output.status != Some(0) {
        return Err(probe_failure(
            output.status,
            &String::from_utf8_lossy(&output.stderr),
        ));
    }
    parse_probe(&String::from_utf8_lossy(&output.stdout))
}

fn has_libs(server_dir: &str) -> bool {
    Path::new(server_dir).join("libs").is_dir()
}

/// The server directories in the work dir, only the ones a download finished in.
fn usable_server_dirs() -> Vec<String> {
    fs::read_dir(".")
        .map(|entries| {
            entries
                .filter_map(|entry| entry.ok())
                .map(|entry| entry.file_name().to_string_lossy().into_owned())
                .filter(|name| has_libs(name))
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
        let mut tried: Vec<String> = Vec::new();
        for candidate in interpreter_candidates(settings, &worktree.root_path(), host_os()) {
            let python = match &candidate {
                Candidate::Configured(path) | Candidate::Venv(path) => path.clone(),
                Candidate::OnPath(name) => match worktree.which(name) {
                    Some(path) => path,
                    None => {
                        tried.push(format!("{name} (not on PATH)"));
                        continue;
                    }
                },
            };
            match probe(&python) {
                Ok(version) => {
                    check_version(version, &python)?;
                    return Ok(python);
                }
                Err(reason) if matches!(candidate, Candidate::Configured(_)) => {
                    return Err(format!(
                        "lsp.pyta-lsp.settings.interpreter is {python}, which could not be run: {reason}. \
                         Fix the path in your Zed settings (use an absolute path, ~ is not expanded)."
                    ));
                }
                Err(reason) => tried.push(format!("{python} ({reason})")),
            }
        }
        Err(format!(
            "No Python was found for PythonTA. Tried {}. Install Python 3.10 or newer, \
             or set lsp.pyta-lsp.settings.interpreter in your Zed settings.",
            tried.join(", ")
        ))
    }

    fn server_libs(&mut self, id: &LanguageServerId, settings: &Settings) -> Result<String> {
        if let Some(dir) = &settings.server_dir {
            return Ok(dir.clone());
        }
        let work_dir = std::env::current_dir()
            .map_err(|error| format!("could not read the extension directory: {error}"))?
            .to_string_lossy()
            .into_owned();
        if let Some(server_dir) = &self.server_dir {
            if has_libs(server_dir) {
                return Ok(libs_dir(&work_dir, server_dir));
            }
        }
        zed::set_language_server_installation_status(
            id,
            &LanguageServerInstallationStatus::CheckingForUpdate,
        );
        let server_dir = match self.install_latest(id) {
            Ok(server_dir) => server_dir,
            // Offline, or the release is not there yet. An earlier download still works.
            Err(error) => {
                let existing = usable_server_dirs();
                match newest_server_dir(existing.iter().map(String::as_str)) {
                    Some(existing) => existing.to_string(),
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
        if has_libs(&dir_name) {
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
        Ok(())
    }
}

impl zed::Extension for PytaExtension {
    fn new() -> Self {
        Self { server_dir: None }
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
        Ok(zed::Command {
            command: python,
            args: SERVER_ARGS.iter().map(|arg| arg.to_string()).collect(),
            env: server_env(worktree.shell_env(), &libs, host_os()),
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
