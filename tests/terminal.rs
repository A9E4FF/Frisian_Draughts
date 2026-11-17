use frisian_draughts::{Game, Outcome, Side};
use std::io::Write;
use std::process::{Command, Stdio};

fn terminal(commands: &str) -> String {
    let mut child = Command::new(env!("CARGO_BIN_EXE_frisian-draughts"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(commands.as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    String::from_utf8(output.stdout).unwrap()
}
#[test]
fn commands_errors_automatic_response_and_exchange_undo() {
    let out = terminal("help\nmoves\nplay 32-99\nplay 31-26\nundo\nboard\ngo\nnew\nquit\n");
    assert!(out.contains("square must be 1–50"));
    assert!(out.contains("Engine:"));
    assert!(!out.contains("Nothing to undo"));
    assert!(out.matches("White to move").count() >= 4);
}
#[test]
fn terminal_automatically_plays_legal_captures() {
    let mut game = Game::default();
    let mut commands = String::new();
    let mut expected_captures = Vec::new();
    for _ in 0..120 {
        if game.outcome() != Outcome::Ongoing {
            break;
        }
        assert_eq!(game.position().turn(), Side::White);
        let mv = game.choose_move().unwrap();
        commands.push_str(&format!("play {mv}\n"));
        game.play(&mv).unwrap();
        if let Some(mv) = game.choose_move() {
            if mv.is_capture() {
                expected_captures.push(format!("Engine: {mv}"));
            }
            game.play(&mv).unwrap();
        }
    }
    commands.push_str("quit\n");
    assert!(!expected_captures.is_empty());
    let out = terminal(&commands);
    for expected in expected_captures {
        assert!(out.contains(&expected));
    }
    assert!(!out.contains("Error:"));
}
