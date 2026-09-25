//! Every decision the extension makes, with no Zed API in it so `cargo test` runs it natively.
//! `lib.rs` feeds these functions what Zed gives it and runs whatever they pick.

use serde_json::Value;

pub const MIN_PYTHON: (u32, u32) = (3, 10);
pub const REPO: &str = "ThePoNGz/pyta-checker";
pub const SERVER_ID: &str = "pyta-lsp";
/// Release assets and the directories they unpack into both start with this.
pub const SERVER_PREFIX: &str = "pyta-lsp-server-";
pub const PROBE: &str = "import sys; print(sys.version_info[0], sys.version_info[1])";
pub const SERVER_ARGS: [&str; 2] = ["-m", "pyta_lsp"];

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

pub fn venv_python(worktree_root: &str, os: Os) -> String {
    let relative = match os {
        Os::Windows => ".venv\\Scripts\\python.exe",
        Os::Mac | Os::Linux => ".venv/bin/python",
    };
    join(worktree_root, relative, os)
}

pub fn interpreter_candidates(settings: &Settings, worktree_root: &str, os: Os) -> Vec<Candidate> {
    if let Some(configured) = &settings.interpreter {
        return vec![Candidate::Configured(configured.clone())];
    }
    let names: [&str; 2] = match os {
        Os::Windows => ["python", "python3"],
        Os::Mac | Os::Linux => ["python3", "python"],
    };
    let mut candidates = vec![Candidate::Venv(venv_python(worktree_root, os))];
    candidates.extend(names.iter().map(|name| Candidate::OnPath(name.to_string())));
    candidates
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PythonVersion {
    pub major: u32,
    pub minor: u32,
}

/// Reads the two numbers the probe prints. Python 2 prints them as a tuple, so
/// anything that isnt a digit is a separator.
pub fn parse_probe(stdout: &str) -> Result<PythonVersion, String> {
    let numbers: Vec<u32> = stdout
        .split(|c: char| !c.is_ascii_digit())
        .filter(|part| !part.is_empty())
        .filter_map(|part| part.parse().ok())
        .collect();
    match numbers.as_slice() {
        [major, minor, ..] => Ok(PythonVersion {
            major: *major,
            minor: *minor,
        }),
        _ => Err(format!(
            "the version probe printed {stdout:?} instead of a version"
        )),
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

pub fn libs_dir(work_dir: &str, server_dir: &str, os: Os) -> String {
    join(&join(work_dir, server_dir, os), "libs", os)
}

/// Variables from the shell that point at some other Python and outrank the one we picked.
const DROPPED: [&str; 4] = ["PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONSTARTUP"];

/// The environment the server runs in: the shell env with the bundle first on
/// PYTHONPATH and the same guards the VS Code client sets.
pub fn server_env(base: Vec<(String, String)>, libs: &str, os: Os) -> Vec<(String, String)> {
    let delimiter = if os == Os::Windows { ';' } else { ':' };
    let mut python_path = libs.to_string();
    let mut env: Vec<(String, String)> = Vec::with_capacity(base.len() + 5);
    for (key, value) in base {
        let upper = key.to_ascii_uppercase();
        if upper == "PYTHONPATH" {
            if !value.is_empty() {
                python_path = format!("{libs}{delimiter}{value}");
            }
            continue;
        }
        if DROPPED.contains(&upper.as_str()) || upper.starts_with("PYTHON") && is_overridden(&upper)
        {
            continue;
        }
        env.push((key, value));
    }
    env.push(("PYTHONPATH".into(), python_path));
    env.push(("PYTHONSAFEPATH".into(), "1".into()));
    env.push(("PYTHONUTF8".into(), "1".into()));
    env.push(("PYTHONIOENCODING".into(), "utf-8".into()));
    env.push(("PYTHONUNBUFFERED".into(), "1".into()));
    env
}

fn is_overridden(key: &str) -> bool {
    matches!(
        key,
        "PYTHONSAFEPATH" | "PYTHONUTF8" | "PYTHONIOENCODING" | "PYTHONUNBUFFERED"
    )
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
            ]
        );
    }

    #[test]
    fn probe_output_parses_on_every_python() {
        assert_eq!(
            parse_probe("3 12\n").unwrap(),
            PythonVersion {
                major: 3,
                minor: 12
            }
        );
        assert_eq!(
            parse_probe("(2, 7)\r\n").unwrap(),
            PythonVersion { major: 2, minor: 7 }
        );
        assert!(parse_probe("").is_err());
        assert!(parse_probe("Python\n").is_err());
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
    fn libs_dir_uses_the_host_separator() {
        assert_eq!(
            libs_dir(
                "/home/me/.local/zed/work/pyta-lsp",
                "pyta-lsp-server-v0.2.0",
                Os::Linux
            ),
            "/home/me/.local/zed/work/pyta-lsp/pyta-lsp-server-v0.2.0/libs"
        );
        assert_eq!(
            libs_dir(
                "C:\\Users\\me\\work\\pyta-lsp\\",
                "pyta-lsp-server-v0.2.0",
                Os::Windows
            ),
            "C:\\Users\\me\\work\\pyta-lsp\\pyta-lsp-server-v0.2.0\\libs"
        );
    }

    fn pairs(env: &[(String, String)]) -> Vec<(&str, &str)> {
        env.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect()
    }

    #[test]
    fn server_env_puts_the_bundle_first_and_drops_the_shell_python_pointers() {
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
                ("PYTHONPATH", "/work/libs:/extra"),
                ("PYTHONSAFEPATH", "1"),
                ("PYTHONUTF8", "1"),
                ("PYTHONIOENCODING", "utf-8"),
                ("PYTHONUNBUFFERED", "1"),
            ]
        );
    }

    #[test]
    fn server_env_without_a_shell_pythonpath_is_just_the_bundle() {
        let env = server_env(
            vec![("Path".into(), "C:\\bin".into())],
            "C:\\work\\libs",
            Os::Windows,
        );
        assert_eq!(pairs(&env)[0], ("Path", "C:\\bin"));
        assert!(pairs(&env).contains(&("PYTHONPATH", "C:\\work\\libs")));
        let env = server_env(
            vec![("PYTHONPATH".into(), "".into())],
            "/work/libs",
            Os::Mac,
        );
        assert!(pairs(&env).contains(&("PYTHONPATH", "/work/libs")));
    }
}
