//! Every decision the extension makes, with no Zed API in it so `cargo test` runs it natively.
//! `lib.rs` feeds these functions what Zed gives it and runs whatever they pick.

use serde_json::Value;

pub const MIN_PYTHON: (u32, u32) = (3, 10);
pub const REPO: &str = "ThePoNGz/pyta-checker";
pub const SERVER_ID: &str = "pyta-lsp";
/// Release assets and the directories they unpack into both start with this.
pub const SERVER_PREFIX: &str = "pyta-lsp-server-";
/// Written into a server directory once its download was checked, so a directory
/// Zed was killed in the middle of unpacking is never taken for a finished one.
pub const INSTALL_MARKER: &str = "installed";
/// Prints the version and the real executable on tagged lines, so the server is
/// started with exactly what answered the probe, not a shim or launcher, and a
/// line a sitecustomize or a .pth file printed first is not read as either.
pub const PROBE: &str = "import sys; print('pyta-probe', sys.version_info[0], sys.version_info[1]); print('pyta-exe', sys.executable)";
const VERSION_TAG: &str = "pyta-probe";
const EXECUTABLE_TAG: &str = "pyta-exe";
/// No -E or -I: the probe runs with the same environment the server will get, so
/// what it reports is what the server sees, and PYTHONUTF8 reaches it, which on
/// Windows is what keeps a non ASCII sys.executable readable.
pub const PROBE_ARGS: [&str; 1] = ["-c"];
/// The server is started with -c rather than -m. With -m the start directory is
/// on sys.path before runpy imports anything, so on 3.10 a types.py in the project
/// root would be imported in place of the standard library one. This line takes
/// the start directory out first and imports nothing until it has. scripts/bundle.py
/// holds the same line for its own check, and a test keeps the two equal.
pub const SERVER_LAUNCHER: &str = "import os, sys; here = os.path.normcase(os.path.realpath(os.getcwd())); sys.path[:] = [p for p in sys.path if p and os.path.normcase(os.path.realpath(p)) != here]; import runpy; runpy.run_module('pyta_lsp', run_name='__main__', alter_sys=True)";
pub const SERVER_ARGS: [&str; 2] = ["-c", SERVER_LAUNCHER];
/// The settings section the server asks for with workspace/configuration.
pub const SERVER_SECTION: &str = "pythonta";
/// The server logs this at startup, which is the one place a note from the
/// extension reliably reaches the user (the language server log in Zed).
pub const NOTICE_VAR: &str = "PYTA_LSP_NOTICE";
/// pyenv reads the project version file from here, so the probe sees the same
/// Python the server will when Zed starts it in the project root.
pub const PYENV_DIR_VAR: &str = "PYENV_DIR";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Os {
    Mac,
    Linux,
    Windows,
}

/// The keys we read out of `lsp.pyta-lsp.settings`.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Settings {
    pub interpreter: Option<String>,
    pub server_dir: Option<String>,
}

fn string_setting(
    object: &serde_json::Map<String, Value>,
    key: &str,
) -> Result<Option<String>, String> {
    match object.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) if text.trim().is_empty() => Ok(None),
        Some(Value::String(text)) => Ok(Some(text.clone())),
        Some(other) => Err(format!(
            "lsp.pyta-lsp.settings.{key} must be a string, not {other}. Fix it in your Zed settings."
        )),
    }
}

pub fn parse_settings(settings: Option<&Value>) -> Result<Settings, String> {
    let object = match settings {
        None | Some(Value::Null) => return Ok(Settings::default()),
        Some(Value::Object(object)) => object,
        Some(other) => {
            return Err(format!(
                "lsp.pyta-lsp.settings must be an object, not {other}. Fix it in your Zed settings."
            ))
        }
    };
    Ok(Settings {
        interpreter: string_setting(object, "interpreter")?,
        server_dir: string_setting(object, "serverDir")?,
    })
}

/// Where a Python might be, in the order we try them.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Candidate {
    /// The `interpreter` setting. When this one fails the user hears about it, we dont move on.
    Configured(String),
    /// The project venv, skipped quietly when it isnt there.
    Venv(String),
    /// A name to look up on PATH.
    OnPath(String),
}

pub fn join(base: &str, tail: &str, os: Os) -> String {
    let separator = if os == Os::Windows { '\\' } else { '/' };
    let trimmed = base.trim_end_matches(['/', '\\']);
    format!("{trimmed}{separator}{tail}")
}

/// The directory a worktree stands for. Zed opens a single file as a worktree
/// whose root is that file, and pyenv aborts when PYENV_DIR is not a directory.
/// Whether the root is a file comes from Zed, since a name proves nothing: a
/// directory can be called discord.py and a script can have no suffix at all.
pub fn project_dir(worktree_root: &str, root_is_file: bool) -> String {
    if !root_is_file {
        return worktree_root.to_string();
    }
    let trimmed = worktree_root.trim_end_matches(['/', '\\']);
    let Some(index) = trimmed.rfind(['/', '\\']) else {
        return worktree_root.to_string();
    };
    let parent = &trimmed[..index];
    if parent.is_empty() || parent.ends_with(':') {
        // A file at the root of the filesystem or of a drive keeps the separator.
        trimmed[..=index].to_string()
    } else {
        parent.to_string()
    }
}

pub fn venv_python(project_dir: &str, os: Os) -> String {
    let relative = match os {
        Os::Windows => ".venv\\Scripts\\python.exe",
        Os::Mac | Os::Linux => ".venv/bin/python",
    };
    join(project_dir, relative, os)
}

/// A usable path from what the probe printed, else the path that was probed.
///
/// On Windows a code page can still garble the line, an embedded Python can leave
/// sys.executable empty, and an MSYS2 Python reports a POSIX path Windows cannot
/// start. Zed can run none of those.
pub fn executable_to_start(probed_path: &str, reported: Option<&str>, os: Os) -> String {
    match reported.map(str::trim) {
        Some(path) if !path.is_empty() && !path.contains('\u{FFFD}') && is_absolute(path, os) => {
            path.to_string()
        }
        _ => probed_path.to_string(),
    }
}

fn is_absolute(path: &str, os: Os) -> bool {
    let bytes = path.as_bytes();
    match os {
        Os::Windows => {
            path.starts_with("\\\\")
                || (bytes.len() > 2
                    && bytes[0].is_ascii_alphabetic()
                    && bytes[1] == b':'
                    && (bytes[2] == b'\\' || bytes[2] == b'/'))
        }
        Os::Mac | Os::Linux => path.starts_with('/'),
    }
}

pub fn interpreter_candidates(settings: &Settings, project_dir: &str, os: Os) -> Vec<Candidate> {
    if let Some(configured) = &settings.interpreter {
        return vec![Candidate::Configured(configured.clone())];
    }
    // Same names and order as the VS Code client. On Windows the py launcher is
    // often the only Python on PATH, and it runs the same server command line.
    let names: &[&str] = match os {
        Os::Windows => &["python", "python3", "py"],
        Os::Mac | Os::Linux => &["python3", "python"],
    };
    let mut candidates = vec![Candidate::Venv(venv_python(project_dir, os))];
    candidates.extend(names.iter().map(|name| Candidate::OnPath(name.to_string())));
    candidates
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PythonVersion {
    pub major: u32,
    pub minor: u32,
}

/// What the probe printed: the version, and the executable when the line was there.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Probed {
    pub version: PythonVersion,
    pub executable: Option<String>,
}

fn tagged_line<'a>(stdout: &'a str, tag: &str) -> Option<&'a str> {
    stdout
        .lines()
        .find_map(|line| line.find(tag).map(|at| &line[at + tag.len()..]))
}

/// Reads the version and the executable off their tagged lines. Python 2 prints
/// each line as a tuple, so on the version line anything that isnt a digit is a
/// separator, and the executable line is stripped of that punctuation too.
pub fn parse_probe(stdout: &str) -> Result<Probed, String> {
    let Some(version_line) = tagged_line(stdout, VERSION_TAG) else {
        return Err(format!(
            "the version probe printed {stdout:?} instead of a version"
        ));
    };
    let numbers: Vec<u32> = version_line
        .split(|c: char| !c.is_ascii_digit())
        .filter(|part| !part.is_empty())
        .filter_map(|part| part.parse().ok())
        .collect();
    let version = match numbers.as_slice() {
        [major, minor, ..] => PythonVersion {
            major: *major,
            minor: *minor,
        },
        _ => {
            return Err(format!(
                "the version probe printed {stdout:?} instead of a version"
            ))
        }
    };
    let executable = tagged_line(stdout, EXECUTABLE_TAG)
        .map(|rest| {
            rest.trim()
                .trim_matches(|c: char| c == '\'' || c == ',' || c == ')' || c == ' ')
                .to_string()
        })
        .filter(|path| !path.is_empty());
    Ok(Probed {
        version,
        executable,
    })
}

/// Whether an `interpreter` setting is a name to look up on PATH rather than a path.
pub fn is_bare_name(interpreter: &str) -> bool {
    !interpreter.contains(['/', '\\'])
}

/// What running the probe on one candidate turned up.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProbeOutcome {
    /// Nothing to run: a PATH name that is not there.
    Missing,
    /// It ran, or failed to start, without printing a version.
    Failed(String),
    /// It answered. The path is what to start the server with.
    Found(PythonVersion, String),
}

fn candidate_label(candidate: &Candidate) -> &str {
    match candidate {
        Candidate::Configured(path) | Candidate::Venv(path) | Candidate::OnPath(path) => path,
    }
}

/// Picks the interpreter the server runs under, given a way to probe each candidate.
///
/// The configured one is the users explicit choice, so when it does not run or is
/// too old the user hears exactly that. The others are guesses, so an old or broken
/// one is noted and the next is tried, which is how the VS Code client behaves too.
pub fn choose_interpreter(
    candidates: &[Candidate],
    mut probe: impl FnMut(&Candidate) -> ProbeOutcome,
) -> Result<String, String> {
    let mut tried: Vec<String> = Vec::new();
    for candidate in candidates {
        let label = candidate_label(candidate);
        let configured = matches!(candidate, Candidate::Configured(_));
        match probe(candidate) {
            ProbeOutcome::Found(version, executable) => {
                if (version.major, version.minor) >= MIN_PYTHON {
                    return Ok(executable);
                }
                if configured {
                    return Err(check_version(version, label).unwrap_err());
                }
                tried.push(format!(
                    "{label} (Python {}.{})",
                    version.major, version.minor
                ));
            }
            ProbeOutcome::Missing if configured => {
                return Err(format!(
                    "lsp.pyta-lsp.settings.interpreter is {label}, which is not on PATH. \
                     Fix it in your Zed settings, or use an absolute path (~ is not expanded)."
                ));
            }
            ProbeOutcome::Missing => tried.push(format!("{label} (not on PATH)")),
            ProbeOutcome::Failed(reason) if configured => {
                return Err(format!(
                    "lsp.pyta-lsp.settings.interpreter is {label}, which could not be run: {reason}. \
                     Fix the path in your Zed settings (use an absolute path, ~ is not expanded)."
                ));
            }
            ProbeOutcome::Failed(reason) => tried.push(format!("{label} ({reason})")),
        }
    }
    Err(format!(
        "No Python {}.{} or newer was found for PythonTA. Tried {}. Install a newer Python, \
         or set lsp.pyta-lsp.settings.interpreter in your Zed settings.",
        MIN_PYTHON.0,
        MIN_PYTHON.1,
        tried.join(", ")
    ))
}

/// What to tell the user when the probe ran but did not print a version.
pub fn probe_failure(status: Option<i32>, stderr: &str) -> String {
    let reason = match status {
        Some(code) => format!("exit code {code}"),
        None => "killed by a signal".to_string(),
    };
    match stderr.lines().map(str::trim).find(|line| !line.is_empty()) {
        Some(line) => format!("{reason}: {line}"),
        None => reason,
    }
}

pub fn check_version(version: PythonVersion, python: &str) -> Result<(), String> {
    if (version.major, version.minor) >= MIN_PYTHON {
        return Ok(());
    }
    Err(format!(
        "PythonTA needs Python {}.{} or newer, but {python} is Python {}.{}. \
         Install a newer Python, or point lsp.pyta-lsp.settings.interpreter in your Zed settings at one.",
        MIN_PYTHON.0, MIN_PYTHON.1, version.major, version.minor
    ))
}

pub fn pick_asset<'a>(names: impl IntoIterator<Item = &'a str>) -> Option<&'a str> {
    names
        .into_iter()
        .find(|name| name.starts_with(SERVER_PREFIX) && name.ends_with(".tar.gz"))
}

pub fn server_dir_name(tag: &str) -> String {
    format!("{SERVER_PREFIX}{tag}")
}

/// The numbers in a server directory name, so v0.10.0 sorts after v0.9.0.
fn version_key(name: &str) -> Vec<u32> {
    name.strip_prefix(SERVER_PREFIX)
        .unwrap_or("")
        .split(|c: char| !c.is_ascii_digit())
        .filter_map(|part| part.parse().ok())
        .collect()
}

pub fn is_server_dir(name: &str) -> bool {
    name.starts_with(SERVER_PREFIX)
}

pub fn newest_server_dir<'a>(names: impl IntoIterator<Item = &'a str>) -> Option<&'a str> {
    names
        .into_iter()
        .filter(|name| is_server_dir(name))
        .max_by_key(|name| version_key(name))
}

pub fn stale_server_dirs<'a>(names: impl IntoIterator<Item = &'a str>, keep: &str) -> Vec<&'a str> {
    names
        .into_iter()
        .filter(|name| is_server_dir(name) && *name != keep)
        .collect()
}

/// Zed hands the extension its work directory (PWD) with forward slashes on
/// every OS, and Python accepts them everywhere, so this never uses the host separator.
pub fn libs_dir(work_dir: &str, server_dir: &str) -> String {
    let trimmed = work_dir.trim_end_matches('/');
    format!("{trimmed}/{server_dir}/libs")
}

/// Why the server could not be fetched from GitHub.
#[derive(Debug, PartialEq, Eq)]
pub enum FetchError {
    /// The newest release predates the tarball, so nothing can be downloaded from it.
    NoTarball { tag: String },
    /// The lookup or the download itself failed.
    Failed(String),
}

impl FetchError {
    pub fn message(&self) -> String {
        match self {
            FetchError::NoTarball { tag } => format!(
                "The latest pyta-checker release ({tag}) has no server tarball, so this extension \
                 needs a newer release. Until then, point lsp.pyta-lsp.settings.serverDir in your \
                 Zed settings at a local libs directory."
            ),
            FetchError::Failed(reason) => format!(
                "Could not get the PythonTA server: {reason}. Check your connection, or point \
                 lsp.pyta-lsp.settings.serverDir in your Zed settings at a local libs directory."
            ),
        }
    }
}

/// The workspace configuration Zed sends the server right after initialize.
///
/// The server answers a change of configuration by asking for the `pythonta`
/// section and falls back to whatever the notification carried, and either way
/// it replaces every setting it has. So this holds the same options the server
/// was initialized with, under the section name it asks for, and the initialization
/// options stay in force instead of being reset to the defaults on every start.
pub fn workspace_configuration(initialization_options: Option<Value>) -> Value {
    let options = match initialization_options {
        Some(Value::Object(object)) => Value::Object(object),
        _ => Value::Object(serde_json::Map::new()),
    };
    let mut wrapped = serde_json::Map::new();
    wrapped.insert(SERVER_SECTION.to_string(), options);
    Value::Object(wrapped)
}

/// Variables from the shell that point at some other Python and outrank the one we
/// picked. Zed lays the shell env back over whatever we return, so a variable we
/// left out comes straight back. Setting it empty is what sticks, and Python
/// treats an empty value as unset.
const EMPTIED: [&str; 4] = ["PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONSTARTUP"];
const FORCED: [(&str, &str); 4] = [
    ("PYTHONSAFEPATH", "1"),
    ("PYTHONUTF8", "1"),
    ("PYTHONIOENCODING", "utf-8"),
    ("PYTHONUNBUFFERED", "1"),
];

/// The environment the server runs in: the shell env with the bundle first on
/// PYTHONPATH and the same guards the VS Code client sets.
///
/// Windows env keys are case insensitive but Zed merges by exact string, so a
/// value goes out under the spelling the shell used, or two keys would race.
pub fn server_env(base: Vec<(String, String)>, libs: &str, os: Os) -> Vec<(String, String)> {
    python_env(base, os, Some(libs))
}

/// The environment the version probe runs in: the same as the server, without a
/// PYTHONPATH of ours (the bundle is not known yet, and the probe imports nothing
/// a project could shadow), plus the project directory for pyenv.
pub fn probe_env(base: Vec<(String, String)>, os: Os, project_dir: &str) -> Vec<(String, String)> {
    let mut env = python_env(base, os, None);
    env.push((PYENV_DIR_VAR.to_string(), project_dir.to_string()));
    env
}

fn python_env(base: Vec<(String, String)>, os: Os, libs: Option<&str>) -> Vec<(String, String)> {
    let delimiter = if os == Os::Windows { ';' } else { ':' };
    let mut env: Vec<(String, String)> = Vec::with_capacity(base.len() + 5);
    let mut python_path_key: Option<String> = None;
    let mut python_path = libs.map(str::to_string);
    let mut forced_seen: Vec<&str> = Vec::new();
    for (key, value) in base {
        let upper = key.to_ascii_uppercase();
        if upper == "PYTHONPATH" {
            if let (Some(libs), false) = (libs, value.is_empty()) {
                python_path = Some(format!("{libs}{delimiter}{value}"));
            }
            python_path_key = Some(key);
            continue;
        }
        if EMPTIED.contains(&upper.as_str()) {
            env.push((key, String::new()));
            continue;
        }
        if let Some((name, forced)) = FORCED.iter().find(|(name, _)| *name == upper) {
            forced_seen.push(name);
            env.push((key, forced.to_string()));
            continue;
        }
        env.push((key, value));
    }
    if let Some(python_path) = python_path {
        env.push((
            python_path_key.unwrap_or_else(|| "PYTHONPATH".to_string()),
            python_path,
        ));
    }
    for (name, forced) in FORCED {
        if !forced_seen.contains(&name) {
            env.push((name.to_string(), forced.to_string()));
        }
    }
    env
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn settings(value: Value) -> Result<Settings, String> {
        parse_settings(Some(&value))
    }

    #[test]
    fn settings_default_when_absent_or_empty() {
        assert_eq!(parse_settings(None).unwrap(), Settings::default());
        assert_eq!(settings(json!(null)).unwrap(), Settings::default());
        assert_eq!(settings(json!({})).unwrap(), Settings::default());
        assert_eq!(
            settings(json!({"interpreter": "", "serverDir": "  "})).unwrap(),
            Settings::default()
        );
    }

    #[test]
    fn settings_read_both_keys_and_ignore_the_rest() {
        let parsed = settings(json!({
            "interpreter": "/opt/py/bin/python",
            "serverDir": "/src/pyta-checker/bundled/libs",
            "runOnSave": false
        }))
        .unwrap();
        assert_eq!(parsed.interpreter.as_deref(), Some("/opt/py/bin/python"));
        assert_eq!(
            parsed.server_dir.as_deref(),
            Some("/src/pyta-checker/bundled/libs")
        );
    }

    #[test]
    fn settings_reject_the_wrong_types_by_name() {
        let err = settings(json!({"interpreter": 3})).unwrap_err();
        assert!(err.contains("lsp.pyta-lsp.settings.interpreter"), "{err}");
        let err = settings(json!({"serverDir": ["a"]})).unwrap_err();
        assert!(err.contains("lsp.pyta-lsp.settings.serverDir"), "{err}");
        let err = settings(json!("a string")).unwrap_err();
        assert!(err.contains("must be an object"), "{err}");
    }

    #[test]
    fn a_configured_interpreter_is_the_only_candidate() {
        let configured = Settings {
            interpreter: Some("/opt/py/bin/python".into()),
            server_dir: None,
        };
        assert_eq!(
            interpreter_candidates(&configured, "/proj", Os::Linux),
            vec![Candidate::Configured("/opt/py/bin/python".into())]
        );
    }

    #[test]
    fn candidates_try_the_venv_then_path_in_os_order() {
        let none = Settings::default();
        assert_eq!(
            interpreter_candidates(&none, "/proj", Os::Linux),
            vec![
                Candidate::Venv("/proj/.venv/bin/python".into()),
                Candidate::OnPath("python3".into()),
                Candidate::OnPath("python".into()),
            ]
        );
        assert_eq!(
            interpreter_candidates(&none, "/proj/", Os::Mac)[0],
            Candidate::Venv("/proj/.venv/bin/python".into())
        );
        assert_eq!(
            interpreter_candidates(&none, "C:\\proj", Os::Windows),
            vec![
                Candidate::Venv("C:\\proj\\.venv\\Scripts\\python.exe".into()),
                Candidate::OnPath("python".into()),
                Candidate::OnPath("python3".into()),
                Candidate::OnPath("py".into()),
            ]
        );
    }

    #[test]
    fn probe_output_parses_on_every_python() {
        assert_eq!(
            parse_probe("pyta-probe 3 12\npyta-exe /usr/bin/python3.12\n").unwrap(),
            Probed {
                version: PythonVersion {
                    major: 3,
                    minor: 12
                },
                executable: Some("/usr/bin/python3.12".into()),
            }
        );
        assert_eq!(
            parse_probe("pyta-probe 3 13\r\npyta-exe C:\\Program Files\\Python313\\python.exe\r\n")
                .unwrap()
                .executable
                .as_deref(),
            Some("C:\\Program Files\\Python313\\python.exe")
        );
        // Python 2 prints each line as a tuple.
        let old =
            parse_probe("('pyta-probe', 2, 7)\r\n('pyta-exe', '/usr/bin/python')\r\n").unwrap();
        assert_eq!(old.version, PythonVersion { major: 2, minor: 7 });
        assert_eq!(old.executable.as_deref(), Some("/usr/bin/python"));
        // Whatever site or a .pth file prints first is ignored.
        let noisy =
            parse_probe("loaded 3 hooks in 0.2s\npyta-probe 3 11\npyta-exe /opt/py/bin/python3\n")
                .unwrap();
        assert_eq!(
            noisy.version,
            PythonVersion {
                major: 3,
                minor: 11
            }
        );
        assert_eq!(noisy.executable.as_deref(), Some("/opt/py/bin/python3"));
        assert_eq!(parse_probe("pyta-probe 3 10\n").unwrap().executable, None);
        assert!(parse_probe("").is_err());
        assert!(parse_probe("Python 3.12.1\n").is_err());
        assert!(parse_probe("pyta-probe three\n").is_err());
    }

    #[test]
    fn a_single_file_worktree_stands_for_its_directory() {
        assert_eq!(
            project_dir("/home/me/csc148/a1/tally.py", true),
            "/home/me/csc148/a1"
        );
        assert_eq!(project_dir("/home/me/bin/deploy", true), "/home/me/bin");
        assert_eq!(
            project_dir("C:\\Users\\me\\a1\\tally.PY", true),
            "C:\\Users\\me\\a1"
        );
        assert_eq!(
            project_dir("/home/me/code/discord.py", false),
            "/home/me/code/discord.py"
        );
        assert_eq!(
            project_dir("/home/me/csc148/a1/", false),
            "/home/me/csc148/a1/"
        );
        assert_eq!(project_dir("/tally.py", true), "/");
        assert_eq!(project_dir("C:\\tally.py", true), "C:\\");
        assert_eq!(project_dir("tally.py", true), "tally.py");
        assert_eq!(
            venv_python("/home/me/a1", Os::Linux),
            "/home/me/a1/.venv/bin/python"
        );
    }

    #[test]
    fn the_executable_to_start_falls_back_to_the_probed_path() {
        assert_eq!(
            executable_to_start(
                "/usr/bin/python3",
                Some("/opt/py/bin/python3.12\n"),
                Os::Linux
            ),
            "/opt/py/bin/python3.12"
        );
        assert_eq!(
            executable_to_start(
                "C:\\py\\python.exe",
                Some("C:\\Users\\Jos\u{FFFD}\\python.exe"),
                Os::Windows
            ),
            "C:\\py\\python.exe"
        );
        assert_eq!(
            executable_to_start("/usr/bin/python3", Some(""), Os::Linux),
            "/usr/bin/python3"
        );
        assert_eq!(
            executable_to_start("/usr/bin/python3", Some("python3"), Os::Linux),
            "/usr/bin/python3"
        );
        assert_eq!(
            executable_to_start("/usr/bin/python3", None, Os::Mac),
            "/usr/bin/python3"
        );
        assert_eq!(
            executable_to_start(
                "C:\\py\\python.exe",
                Some("C:/Python312/python.exe"),
                Os::Windows
            ),
            "C:/Python312/python.exe"
        );
        assert_eq!(
            executable_to_start(
                "C:\\py\\python.exe",
                Some("\\\\server\\share\\python.exe"),
                Os::Windows
            ),
            "\\\\server\\share\\python.exe"
        );
        // An MSYS2 Python answers with a POSIX path that Windows cannot start.
        assert_eq!(
            executable_to_start(
                "C:\\msys64\\usr\\bin\\python3.exe",
                Some("/usr/bin/python3"),
                Os::Windows
            ),
            "C:\\msys64\\usr\\bin\\python3.exe"
        );
        assert_eq!(
            executable_to_start("/usr/bin/python3", Some("C:\\py\\python.exe"), Os::Linux),
            "/usr/bin/python3"
        );
    }

    #[test]
    fn the_probe_env_is_the_server_env_without_a_pythonpath() {
        let base = vec![
            ("PATH".to_string(), "/usr/bin".to_string()),
            ("PYTHONPATH".to_string(), "/proj".to_string()),
            ("PYTHONHOME".to_string(), "/old".to_string()),
        ];
        let env = probe_env(base, Os::Linux, "/proj");
        assert_eq!(
            pairs(&env),
            vec![
                ("PATH", "/usr/bin"),
                ("PYTHONHOME", ""),
                ("PYTHONSAFEPATH", "1"),
                ("PYTHONUTF8", "1"),
                ("PYTHONIOENCODING", "utf-8"),
                ("PYTHONUNBUFFERED", "1"),
                ("PYENV_DIR", "/proj"),
            ]
        );
    }

    #[test]
    fn bare_names_are_told_apart_from_paths() {
        assert!(is_bare_name("python3.12"));
        assert!(is_bare_name("py"));
        assert!(!is_bare_name("/usr/bin/python3"));
        assert!(!is_bare_name("C:\\Python312\\python.exe"));
        assert!(!is_bare_name("./venv/bin/python"));
    }

    fn version(major: u32, minor: u32) -> PythonVersion {
        PythonVersion { major, minor }
    }

    #[test]
    fn choosing_skips_old_and_broken_guesses_and_keeps_going() {
        let candidates = vec![
            Candidate::Venv("/proj/.venv/bin/python".into()),
            Candidate::OnPath("python3".into()),
            Candidate::OnPath("python".into()),
        ];
        let chosen = choose_interpreter(&candidates, |candidate| match candidate {
            Candidate::Venv(_) => ProbeOutcome::Failed("No such file (os error 2)".into()),
            Candidate::OnPath(name) if name == "python3" => {
                ProbeOutcome::Found(version(3, 9), "/usr/bin/python3.9".into())
            }
            _ => ProbeOutcome::Found(version(3, 12), "/opt/py/bin/python3.12".into()),
        });
        assert_eq!(chosen.unwrap(), "/opt/py/bin/python3.12");
    }

    #[test]
    fn choosing_reports_everything_it_tried_when_nothing_fits() {
        let candidates = vec![
            Candidate::Venv("C:\\proj\\.venv\\Scripts\\python.exe".into()),
            Candidate::OnPath("python".into()),
            Candidate::OnPath("py".into()),
        ];
        let err = choose_interpreter(&candidates, |candidate| match candidate {
            Candidate::Venv(_) => ProbeOutcome::Failed("not found".into()),
            Candidate::OnPath(name) if name == "python" => {
                ProbeOutcome::Found(version(3, 8), "C:\\Python38\\python.exe".into())
            }
            _ => ProbeOutcome::Missing,
        })
        .unwrap_err();
        assert!(
            err.starts_with("No Python 3.10 or newer was found"),
            "{err}"
        );
        assert!(err.contains("python.exe (not found)"), "{err}");
        assert!(err.contains("python (Python 3.8)"), "{err}");
        assert!(err.contains("py (not on PATH)"), "{err}");
        assert!(err.contains("lsp.pyta-lsp.settings.interpreter"), "{err}");
    }

    #[test]
    fn a_configured_interpreter_is_never_silently_replaced() {
        let configured = vec![Candidate::Configured("/opt/old/python".into())];
        let err = choose_interpreter(&configured, |_| {
            ProbeOutcome::Found(version(3, 9), "/opt/old/python".into())
        })
        .unwrap_err();
        assert!(err.contains("/opt/old/python is Python 3.9"), "{err}");
        let err = choose_interpreter(&configured, |_| ProbeOutcome::Failed("exit code 1".into()))
            .unwrap_err();
        assert!(err.contains("could not be run: exit code 1"), "{err}");
        let err = choose_interpreter(&configured, |_| ProbeOutcome::Missing).unwrap_err();
        assert!(err.contains("is not on PATH"), "{err}");
        let ok = choose_interpreter(&configured, |_| {
            ProbeOutcome::Found(version(3, 11), "/opt/old/python".into())
        });
        assert_eq!(ok.unwrap(), "/opt/old/python");
    }

    #[test]
    fn the_launcher_line_matches_the_one_bundle_py_checks() {
        // The Python side cannot import this crate, so the two copies are kept
        // equal here instead.
        let bundle = include_str!("../../scripts/bundle.py");
        assert!(
            bundle.contains(SERVER_LAUNCHER),
            "scripts/bundle.py SERVER_LAUNCHER differs"
        );
        assert_eq!(SERVER_ARGS[0], "-c");
    }

    #[test]
    fn versions_below_the_minimum_are_refused_with_both_numbers() {
        let ok = PythonVersion {
            major: 3,
            minor: 10,
        };
        assert!(check_version(ok, "/usr/bin/python3").is_ok());
        let err =
            check_version(PythonVersion { major: 3, minor: 9 }, "/usr/bin/python3").unwrap_err();
        assert!(err.contains("3.10"), "{err}");
        assert!(err.contains("/usr/bin/python3 is Python 3.9"), "{err}");
        assert!(err.contains("lsp.pyta-lsp.settings.interpreter"), "{err}");
        assert!(check_version(PythonVersion { major: 2, minor: 7 }, "python").is_err());
        assert!(check_version(PythonVersion { major: 4, minor: 0 }, "python").is_ok());
    }

    #[test]
    fn the_server_asset_is_picked_by_prefix() {
        let names = [
            "pyta-checker-v0.2.0.vsix",
            "pyta-lsp-server-0.2.0.tar.gz.sha256",
            "pyta-lsp-server-0.2.0.tar.gz",
        ];
        assert_eq!(pick_asset(names), Some("pyta-lsp-server-0.2.0.tar.gz"));
        assert_eq!(pick_asset(["pyta-checker-v0.2.0.vsix"]), None);
    }

    #[test]
    fn server_dirs_are_named_after_the_tag_and_sorted_by_version() {
        assert_eq!(server_dir_name("v0.2.0"), "pyta-lsp-server-v0.2.0");
        let names = [
            "pyta-lsp-server-v0.9.0",
            "pyta-lsp-server-v0.10.0",
            "pyta-lsp-server-v0.2.1",
            "something-else",
        ];
        assert_eq!(newest_server_dir(names), Some("pyta-lsp-server-v0.10.0"));
        assert_eq!(newest_server_dir(["something-else"]), None);
        assert_eq!(
            stale_server_dirs(names, "pyta-lsp-server-v0.10.0"),
            vec!["pyta-lsp-server-v0.9.0", "pyta-lsp-server-v0.2.1"]
        );
    }

    #[test]
    fn libs_dir_uses_forward_slashes_like_the_work_dir_zed_gives() {
        assert_eq!(
            libs_dir(
                "/home/me/.local/zed/work/pyta-lsp",
                "pyta-lsp-server-v0.2.0"
            ),
            "/home/me/.local/zed/work/pyta-lsp/pyta-lsp-server-v0.2.0/libs"
        );
        assert_eq!(
            libs_dir("C:/Users/me/work/pyta-lsp/", "pyta-lsp-server-v0.2.0"),
            "C:/Users/me/work/pyta-lsp/pyta-lsp-server-v0.2.0/libs"
        );
    }

    #[test]
    fn probe_failures_name_the_exit_and_the_first_stderr_line() {
        assert_eq!(
            probe_failure(Some(2), "Unknown option: -X\nusage: python [option] ...\n"),
            "exit code 2: Unknown option: -X"
        );
        assert_eq!(probe_failure(Some(1), "\n  \n"), "exit code 1");
        assert_eq!(probe_failure(None, ""), "killed by a signal");
    }

    #[test]
    fn fetch_errors_tell_the_user_what_to_do() {
        let no_tarball = FetchError::NoTarball {
            tag: "v0.1.0".into(),
        }
        .message();
        assert!(no_tarball.contains("v0.1.0"), "{no_tarball}");
        assert!(no_tarball.contains("newer release"), "{no_tarball}");
        assert!(!no_tarball.contains("connection"), "{no_tarball}");
        let failed = FetchError::Failed("timed out".into()).message();
        assert!(failed.contains("timed out"), "{failed}");
        assert!(failed.contains("connection"), "{failed}");
        assert!(failed.contains("serverDir"), "{failed}");
    }

    #[test]
    fn workspace_configuration_wraps_the_initialization_options_in_the_server_section() {
        let options = json!({"runOnSave": false, "configPath": "config/.pylintrc"});
        assert_eq!(
            workspace_configuration(Some(options.clone())),
            json!({"pythonta": options})
        );
        assert_eq!(workspace_configuration(None), json!({"pythonta": {}}));
        assert_eq!(
            workspace_configuration(Some(json!("not an object"))),
            json!({"pythonta": {}})
        );
    }

    fn pairs(env: &[(String, String)]) -> Vec<(&str, &str)> {
        env.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect()
    }

    #[test]
    fn server_env_puts_the_bundle_first_and_empties_the_shell_python_pointers() {
        let base = vec![
            ("PATH".to_string(), "/usr/bin".to_string()),
            ("VIRTUAL_ENV".to_string(), "/proj/.venv".to_string()),
            ("PYTHONPATH".to_string(), "/extra".to_string()),
            ("PYTHONSAFEPATH".to_string(), "".to_string()),
            ("CONDA_PREFIX".to_string(), "/conda".to_string()),
        ];
        let env = server_env(base, "/work/libs", Os::Linux);
        assert_eq!(
            pairs(&env),
            vec![
                ("PATH", "/usr/bin"),
                ("VIRTUAL_ENV", ""),
                ("PYTHONSAFEPATH", "1"),
                ("CONDA_PREFIX", ""),
                ("PYTHONPATH", "/work/libs:/extra"),
                ("PYTHONUTF8", "1"),
                ("PYTHONIOENCODING", "utf-8"),
                ("PYTHONUNBUFFERED", "1"),
            ]
        );
    }

    #[test]
    fn server_env_keeps_the_shell_spelling_of_a_windows_key() {
        // Zed merges by exact key and Windows reads keys case insensitively, so a
        // second spelling of the same variable would leave the winner to chance.
        let base = vec![
            ("Path".to_string(), "C:\\bin".to_string()),
            ("PythonPath".to_string(), "C:\\mylibs".to_string()),
            ("PythonHome".to_string(), "C:\\old".to_string()),
            ("pythonutf8".to_string(), "0".to_string()),
        ];
        let env = server_env(base, "C:/work/libs", Os::Windows);
        assert_eq!(
            pairs(&env),
            vec![
                ("Path", "C:\\bin"),
                ("PythonHome", ""),
                ("pythonutf8", "1"),
                ("PythonPath", "C:/work/libs;C:\\mylibs"),
                ("PYTHONSAFEPATH", "1"),
                ("PYTHONIOENCODING", "utf-8"),
                ("PYTHONUNBUFFERED", "1"),
            ]
        );
        let python_paths = pairs(&env)
            .iter()
            .filter(|(k, _)| k.eq_ignore_ascii_case("pythonpath"))
            .count();
        assert_eq!(python_paths, 1);
    }

    #[test]
    fn server_env_without_a_shell_pythonpath_is_just_the_bundle() {
        let env = server_env(
            vec![("Path".into(), "C:\\bin".into())],
            "C:/work/libs",
            Os::Windows,
        );
        assert_eq!(pairs(&env)[0], ("Path", "C:\\bin"));
        assert!(pairs(&env).contains(&("PYTHONPATH", "C:/work/libs")));
        let env = server_env(
            vec![("PYTHONPATH".into(), "".into())],
            "/work/libs",
            Os::Mac,
        );
        assert!(pairs(&env).contains(&("PYTHONPATH", "/work/libs")));
    }
}
