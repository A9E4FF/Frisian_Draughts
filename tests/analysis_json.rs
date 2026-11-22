use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Stdio};
fn request(value: Value) -> Vec<Value> {
    let mut child = Command::new(env!("CARGO_BIN_EXE_frisian-draughts"))
        .arg("--analysis-json")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    writeln!(child.stdin.take().unwrap(), "{value}").unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|s| serde_json::from_str(s).unwrap())
        .collect()
}
#[test]
fn imports_fen_and_accepts_any_of_multiple_legal_answers() {
    let events = request(
        json!({"command":"analyze","fen":"W:W31:B16","depth":1,"accepted_moves":["31-26","31-27"]}),
    );
    assert_eq!(events[0]["type"], "loaded");
    assert_eq!(events[0]["hub"].as_str().unwrap().len(), 51);
    assert_eq!(events[0]["outcome"], "ongoing");
    assert_eq!(events[0]["pieces"].as_array().unwrap().len(), 2);
    assert!(!events[0]["warnings"].as_array().unwrap().is_empty());
    assert!(events.iter().any(|e| e["type"] == "iteration"));
    let result = events.last().unwrap();
    assert_eq!(result["type"], "result");
    assert_eq!(result["best_move"], "31-27");
    assert_eq!(result["passed"], true);
    for field in [
        "tt_probes",
        "tt_hits",
        "tt_cutoffs",
        "nodes",
        "quiescence_nodes",
        "elapsed_ms",
    ] {
        assert!(result[field].is_number());
    }
}
#[test]
fn invalid_fen_expected_moves_and_replay_fail_before_search() {
    for input in [
        json!({"fen":"broken"}),
        json!({"fen":"W:W31:B16","accepted_moves":["31-99"]}),
        json!({"fen":"W:W31:B16","moves":["31-99"]}),
        json!({"fen":"W:W31:B16","depth":65}),
        json!({"fen":"W:W31:B16","restrictions":{"white":{"square":31,"count":2}}}),
    ] {
        let events = request(input);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["type"], "error");
    }
}
#[test]
fn inspect_retains_supplied_restrictions_and_replays_moves() {
    let events = request(json!({"command":"inspect","fen":"W:WK28,46:BK5,1",
        "restrictions":{"white":{"square":28,"count":2}},"moves":["28-22"]}));
    assert_eq!(events.len(), 1);
    assert_eq!(events[0]["type"], "loaded");
    assert_eq!(events[0]["turn"], "black");
    assert_eq!(
        events[0]["restrictions"]["white"],
        json!({"square":22,"count":3})
    );
}
#[test]
fn replay_preserves_repetition_and_sole_moves_are_unsearched() {
    let moves = [
        "1-12", "5-10", "12-1", "10-5", "1-12", "5-10", "12-1", "10-5",
    ];
    let events = request(json!({"fen":"W:WK1:BK5","moves":moves,"depth":2}));
    let result = events.last().unwrap();
    assert_eq!(result["type"], "result");
    assert_eq!(result["score"], 0);
    assert!(result["best_move"].is_null());
    assert!(result["passed"].is_null());
    let events = request(json!({"fen":"W:W28:B23","accepted_moves":["28x19"],"depth":10}));
    let result = events.last().unwrap();
    assert_eq!(result["depth"], 0);
    assert!(result["score"].is_null());
    assert_eq!(result["passed"], true);
    assert_eq!(result["nodes"], 0);
}
#[test]
fn reports_completed_iterations_and_can_disable_tt() {
    let events = request(json!({"fen":"W:W31-50:B1-20","depth":3,"tt_enabled":false}));
    let iterations: Vec<_> = events.iter().filter(|e| e["type"] == "iteration").collect();
    assert_eq!(iterations.len(), 3);
    for (i, e) in iterations.iter().enumerate() {
        assert_eq!(e["depth"], i + 1);
        assert_eq!(e["tt_probes"], 0);
    }
    assert_eq!(events.last().unwrap()["depth"], 3);
}

#[test]
fn legal_but_unselected_expected_move_is_a_failure_not_an_error() {
    let events = request(json!({"fen":"W:W31:B16","depth":1,"accepted_moves":["31-26"]}));
    assert_eq!(events[0]["type"], "loaded");
    let result = events.last().unwrap();
    assert_eq!(result["type"], "result");
    assert_eq!(result["best_move"], "31-27");
    assert_eq!(result["passed"], false);
}

#[test]
fn forced_root_analysis_and_zero_time_are_distinct_from_playing_shortcut() {
    let request_forced = |time| {
        request(
            json!({"fen":"W:W28:B23","depth":3,"search_forced_root":true,
            "time_limit_ms":time}),
        )
    };
    let events = request_forced(10_000);
    let result = events.last().unwrap();
    assert_eq!(result["status"], "completed");
    assert_eq!(result["depth"], 3);
    assert_eq!(result["score"], 29_999);
    assert_eq!(result["best_move"], "28x19");
    let events = request_forced(0);
    let result = events.last().unwrap();
    assert_eq!(result["status"], "time_limit");
    assert_eq!(result["depth"], 0);
    assert!(result["score"].is_null());
    assert!(!events.iter().any(|event| event["type"] == "iteration"));
}
