use frisian_draughts::hub::{parse, run};
use frisian_draughts::{Game, Position};
use std::io::Cursor;

fn transcript(commands: &str) -> Vec<String> {
    let mut out = Vec::new();
    run(Cursor::new(commands), &mut out).unwrap();
    String::from_utf8(out)
        .unwrap()
        .lines()
        .map(str::to_owned)
        .collect()
}
#[test]
fn codec_and_positions_round_trip() {
    let m = parse("info pv=\"31-26 16-21\" flag field = \"a=b\"").unwrap();
    assert_eq!(m.get("pv"), Some("31-26 16-21"));
    assert!(m.has("flag"));
    assert_eq!(m.get("field"), Some("a=b"));
    for bad in ["", "info a=", "info a=\"unterminated", "info a=\"x\"b=y"] {
        assert!(parse(bad).is_err(), "{bad}");
    }
    for fen in ["W:W31-50:B1-20", "B:WK28,46:BK5,20"] {
        let p = Position::from_fen(fen).unwrap();
        assert_eq!(Position::from_hub(&p.to_hub()).unwrap(), p);
    }
    assert!(Position::from_hub("W:W31-50:B1-20").is_err());
    assert!(Position::from_hub(&format!("W{}", "x".repeat(50))).is_err());
}
#[test]
fn handshake_depth_search_and_legal_pv() {
    let lines = transcript("hub\nset-param name=variant value=frisian\ninit\npos start\nlevel depth=2\ngo think\nping\nquit\n");
    assert!(lines.iter().any(|s| s == "wait"));
    assert!(lines.iter().any(|s| s == "ready"));
    assert_eq!(lines.last().unwrap(), "pong");
    assert!(!lines.iter().any(|s| s.starts_with("error")));
    let mut count = 0;
    for line in &lines {
        let m = parse(line).unwrap();
        if m.command == "info" {
            let mut game = Game::default();
            for text in m.get("pv").unwrap().split_whitespace() {
                let mv = game.position().parse_move(text).unwrap();
                game.play(&mv).unwrap();
            }
            count += 1;
        } else if m.command == "done" {
            Position::starting()
                .parse_move(m.get("move").unwrap())
                .unwrap();
        }
    }
    assert_eq!(count, 2);
}
#[test]
fn illegal_replay_is_atomic_and_limit_errors_are_explicit() {
    let lines = transcript(
        "init\npos start moves=\"31-26 illegal\"\nlevel nodes=5\nlevel depth=1\ngo analyze\nquit\n",
    );
    assert_eq!(lines.iter().filter(|s| s.starts_with("error")).count(), 2);
    let done = lines.iter().find(|s| s.starts_with("done")).unwrap();
    Position::starting()
        .parse_move(parse(done).unwrap().get("move").unwrap())
        .unwrap();
}
#[test]
fn history_replay_detects_repetition() {
    let p = Position::from_fen("W:WK1:BK5").unwrap();
    let lines = transcript(&format!("init\npos pos={} moves=\"1-12 5-10 12-1 10-5 1-12 5-10 12-1 10-5\"\nlevel depth=1\ngo think\nquit\n", p.to_hub()));
    assert!(lines.iter().any(|s| s == "done"));
    assert!(lines.iter().any(|s| s.contains("score=0.00")));
}
