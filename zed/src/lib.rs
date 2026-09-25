//! The thin layer between Zed and `logic.rs`. Finds a Python, fetches the server
//! from a GitHub release and hands Zed the command to run.

mod logic;

use std::fs;
use std::path::Path;

use logic::{
    check_version, interpreter_candidates, libs_dir, newest_server_dir, parse_probe,
    parse_settings, pick_asset, server_dir_name, server_env, stale_server_dirs, Candidate, Os,
    PythonVersion, Settings, PROBE, REPO, SERVER_ARGS, SERVER_ID,
};
use zed_extension_api::settings::LspSettings;
use zed_extension_api::{self as zed, LanguageServerId, LanguageServerInstallationStatus, Result};

struct PytaExtension {
    // The libs directory the last start used, so one Zed session downloads once.
    libs: Option<String>,
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
        .args(["-I", "-c", PROBE])
        .output()?;
    if output.status != Some(0) {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "exit status {:?}: {}",
            output.status,
            stderr.trim()
        ));
    }
    parse_probe(&String::from_utf8_lossy(&output.stdout))
}

fn work_dir_entries() -> Vec<String> {
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
                         Fix the path in your Zed settings."
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
        if let Some(libs) = &self.libs {
            if Path::new(libs).is_dir() {
                return Ok(libs.clone());
            }
        }
        let os = host_os();
        let work_dir = std::env::current_dir()
            .map_err(|error| format!("could not read the extension directory: {error}"))?
            .to_string_lossy()
            .into_owned();
        zed::set_language_server_installation_status(
            id,
            &LanguageServerInstallationStatus::CheckingForUpdate,
        );
        let dir_name = match self.install_latest(id) {
            Ok(dir_name) => dir_name,
            // Offline, or the release is not there yet. An earlier download still works.
            Err(error) => match newest_server_dir(work_dir_entries().iter().map(String::as_str)) {
                Some(existing) => existing.to_string(),
                None => {
                    let message = format!(
                        "Could not get the PythonTA server: {error}. Check your connection, or point \
                         lsp.pyta-lsp.settings.serverDir at a local libs directory."
                    );
                    zed::set_language_server_installation_status(
                        id,
                        &LanguageServerInstallationStatus::Failed(message.clone()),
                    );
                    return Err(message);
                }
            },
        };
        zed::set_language_server_installation_status(id, &LanguageServerInstallationStatus::None);
        let libs = libs_dir(&work_dir, &dir_name, os);
        self.libs = Some(libs.clone());
        Ok(libs)
    }

    /// Downloads the newest release into its own directory and returns that directory name.
    fn install_latest(&self, id: &LanguageServerId) -> Result<String> {
        let release = zed::latest_github_release(
            REPO,
            zed::GithubReleaseOptions {
                require_assets: true,
                pre_release: false,
            },
        )?;
        let asset_name = pick_asset(release.assets.iter().map(|asset| asset.name.as_str()))
            .ok_or_else(|| format!("release {} has no pyta-lsp-server tarball", release.version))?;
        let asset = release
            .assets
            .iter()
            .find(|asset| asset.name == asset_name)
            .expect("the picked asset came from this list");
        let dir_name = server_dir_name(&release.version);
        let dir = Path::new(&dir_name);
        if dir.join("libs").is_dir() {
            return Ok(dir_name);
        }
        zed::set_language_server_installation_status(
            id,
            &LanguageServerInstallationStatus::Downloading,
        );
        // Whatever a broken earlier download left behind must not be mistaken for the real thing.
        if dir.exists() {
            fs::remove_dir_all(dir)
                .map_err(|error| format!("could not clear {dir_name}: {error}"))?;
        }
        zed::download_file(
            &asset.download_url,
            &dir_name,
            zed::DownloadedFileType::GzipTar,
        )
        .map_err(|error| format!("downloading {asset_name} failed: {error}"))?;
        if !dir.join("libs").is_dir() {
            return Err(format!("{asset_name} did not contain a libs directory"));
        }
        let entries = work_dir_entries();
        for stale in stale_server_dirs(entries.iter().map(String::as_str), &dir_name) {
            // Best effort, a leftover only costs disk space.
            let _ = fs::remove_dir_all(stale);
        }
        Ok(dir_name)
    }
}

impl zed::Extension for PytaExtension {
    fn new() -> Self {
        Self { libs: None }
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
        Ok(LspSettings::for_worktree(SERVER_ID, worktree)
            .ok()
            .and_then(|lsp| lsp.settings))
    }
}

zed::register_extension!(PytaExtension);
