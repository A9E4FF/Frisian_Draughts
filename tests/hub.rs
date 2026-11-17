use frisian_draughts::hub::parse;
use frisian_draughts::{Game, Position};
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{channel, Receiver};
use std::time::Duration;

struct Peer {
    child: Child,
    lines: Receiver<String>,
}
impl Peer {
    fn new() -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_frisian-draughts"))
            .arg("hub")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let output = child.stdout.take().unwrap();
        let (tx, lines) = channel();
        std::thread::spawn(move || {
            for line in BufReader::new(output).lines() {
                if tx.send(line.unwrap()).is_err() {
                    break;
                }
            }
        });
        Self { child, lines }
    }
    fn send(&mut self, command: &str) {
        writeln!(self.child.stdin.as_mut().unwrap(), "{command}").unwrap();
    }
    fn until(&self, command: &str) -> Vec<String> {
        let mut lines = Vec::new();
        loop {
            let line = self
                .lines
                .recv_timeout(Duration::from_secs(5))
                .expect("Hub reply deadline");
            let done = parse(&line).unwrap().command == command;
            lines.push(line);
            if done {
                return lines;
            }
        }
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn transcript(commands: &str) -> Vec<String> {
    let mut peer = Peer::new();
    let mut lines = Vec::new();
    for command in commands.lines() {
        peer.send(command);
        let expected = match command.split_whitespace().next().unwrap() {
            "hub" => Some("wait"),
            "init" => Some("ready"),
            "go" => Some("done"),
            "ping" => Some("pong"),
            _ => None,
        };
        if let Some(expected) = expected {
            lines.extend(peer.until(expected));
        }
    }
    lines
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
        "init\npos start moves=\"31-26 illegal\"\nlevel nodes=0\nlevel depth=1\ngo analyze\nquit\n",
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

#[test]
fn ping_stop_restart_and_node_time_limits() {
    let mut peer = Peer::new();
    peer.send("init");
    peer.until("ready");
    peer.send("pos start");
    peer.send("level infinite");
    peer.send("go analyze");
    peer.send("ping");
    peer.until("pong");
    peer.send("stop");
    let lines = peer.until("done");
    let result = parse(lines.last().unwrap()).unwrap();
    Position::starting()
        .parse_move(result.get("move").unwrap())
        .unwrap();
    for control in [
        "level nodes=1",
        "level move-time=0",
        "level time=0 inc=0",
        "level moves=10 time=0.01 inc=0",
    ] {
        peer.send("pos start");
        peer.send(control);
        peer.send("go think");
        let lines = peer.until("done");
        assert!(!lines.iter().any(|s| s.starts_with("error")), "{lines:?}");
        Position::starting()
            .parse_move(parse(lines.last().unwrap()).unwrap().get("move").unwrap())
            .unwrap();
    }
}

#[test]
fn ponder_hit_and_eof_stop_the_worker() {
    let mut peer = Peer::new();
    peer.send("init");
    peer.until("ready");
    peer.send("pos start");
    peer.send("level move-time=0");
    peer.send("go ponder");
    peer.send("ping");
    peer.until("pong");
    peer.send("ponder-hit");
    peer.until("done");
    peer.send("pos start");
    peer.send("level infinite");
    peer.send("go analyze");
    drop(peer.child.stdin.take());
    peer.until("done");
    assert!(peer.child.wait().unwrap().success());
}
