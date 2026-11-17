//! Hub v2 adapter. Protocol reference: Scan 3.1, Fabien Letouzey; GPL-3.0-only.
//! Stage 2 supports depth searches synchronously; other limits are rejected.
use crate::search::{search_with_reporter, SearchLimits, SearchResult};
use crate::{Error, Game, Piece, Position, Side, Square};
use std::io::{self, BufRead, Write};

#[derive(Debug, PartialEq, Eq)]
pub struct Message {
    pub command: String,
    pub pairs: Vec<(String, String)>,
}
impl Message {
    pub fn get(&self, key: &str) -> Option<&str> {
        self.pairs
            .iter()
            .rev()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }
    pub fn has(&self, key: &str) -> bool {
        self.get(key).is_some()
    }
}

fn name_char(c: char) -> bool {
    !c.is_control() && !c.is_whitespace() && c != '=' && c != '"'
}
pub fn parse(line: &str) -> Result<Message, Error> {
    let mut chars = line.trim_end_matches(['\r', '\n']).chars().peekable();
    let error = || Error("malformed Hub message".into());
    fn blanks(chars: &mut std::iter::Peekable<std::str::Chars<'_>>) {
        while chars.peek().is_some_and(|c| c.is_whitespace()) {
            chars.next();
        }
    }
    // Explicit scanner: quoted values have no backslash escaping in Hub v2.
    fn token(chars: &mut std::iter::Peekable<std::str::Chars<'_>>) -> String {
        let mut s = String::new();
        while chars.peek().is_some_and(|&c| name_char(c)) {
            s.push(chars.next().unwrap());
        }
        s
    }
    blanks(&mut chars);
    let command = token(&mut chars);
    if command.is_empty() {
        return Err(error());
    }
    let mut pairs = Vec::new();
    loop {
        blanks(&mut chars);
        if chars.peek().is_none() {
            break;
        }
        let key = token(&mut chars);
        if key.is_empty() {
            return Err(error());
        }
        blanks(&mut chars);
        let mut value = String::new();
        if chars.peek() == Some(&'=') {
            chars.next();
            blanks(&mut chars);
            if chars.peek() == Some(&'"') {
                chars.next();
                loop {
                    match chars.next() {
                        Some('"') => break,
                        Some(c) if !c.is_control() => value.push(c),
                        _ => return Err(error()),
                    }
                }
                if chars.peek().is_some_and(|c| !c.is_whitespace()) {
                    return Err(error());
                }
            } else {
                value = token(&mut chars);
                if value.is_empty() {
                    return Err(error());
                }
            }
        }
        pairs.push((key, value));
    }
    Ok(Message { command, pairs })
}

pub fn quoted(value: &str) -> String {
    // Internal diagnostics may contain user input; replace characters which
    // cannot be represented instead of permitting line/argument injection.
    format!(
        "\"{}\"",
        value
            .chars()
            .map(|c| if c == '"' || c.is_control() { ' ' } else { c })
            .collect::<String>()
    )
}
impl Position {
    /// Hub boards omit king restriction counters and previous history.
    pub fn from_hub(text: &str) -> Result<Self, Error> {
        let bytes = text.as_bytes();
        if bytes.len() != 51 {
            return Err(Error("Hub board requires 51 characters".into()));
        }
        let turn = match bytes[0] {
            b'W' => Side::White,
            b'B' => Side::Black,
            _ => return Err(Error("Hub turn must be W or B".into())),
        };
        let mut pieces = Vec::new();
        for (i, &c) in bytes[1..].iter().enumerate() {
            let (side, piece) = match c {
                b'w' => (Side::White, Piece::Man),
                b'b' => (Side::Black, Piece::Man),
                b'W' => (Side::White, Piece::King),
                b'B' => (Side::Black, Piece::King),
                b'e' => continue,
                _ => return Err(Error("invalid Hub piece".into())),
            };
            pieces.push((Square::new(i as u8 + 1)?, side, piece));
        }
        Self::new(turn, &pieces, [None; 2])
    }
    pub fn to_hub(&self) -> String {
        let mut text = if self.turn() == Side::White { "W" } else { "B" }.to_owned();
        for n in 1..=50 {
            text.push(match self.piece_at(Square::new(n).unwrap()) {
                Some((Side::White, Piece::Man)) => 'w',
                Some((Side::Black, Piece::Man)) => 'b',
                Some((Side::White, Piece::King)) => 'W',
                Some((Side::Black, Piece::King)) => 'B',
                None => 'e',
            });
        }
        text
    }
}

fn emit(out: &mut impl Write, line: &str) -> io::Result<()> {
    writeln!(out, "{line}")?;
    out.flush()
}
fn report(result: &SearchResult) -> String {
    let mut line = format!(
        "info depth={} nodes={} time={:.6} nps={:.6}",
        result.completed_depth,
        result.nodes,
        result.elapsed.as_secs_f64(),
        result.nodes as f64 / result.elapsed.as_secs_f64().max(0.000001) / 1_000_000.0
    );
    if let Some(score) = result.score {
        line.push_str(&format!(" score={:.2}", score as f64 / 100.0));
    }
    let pv = result
        .principal_variation
        .iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>()
        .join(" ");
    line.push_str(&format!(" pv={}", quoted(&pv)));
    line
}

/// Blocking depth-only adapter. Existing terminal and JSON modes are separate.
pub fn run(input: impl BufRead, mut output: impl Write) -> io::Result<()> {
    let mut game = Game::default();
    let mut limits = SearchLimits::default();
    let mut ready = false;
    for line in input.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let result = (|| -> Result<(), Error> {
            let m = parse(&line)?;
            match m.command.as_str() {
                "hub" => {
                    emit(
                        &mut output,
                        &format!(
                            "id name=Frisian-Draughts version={} author=Contributors",
                            env!("CARGO_PKG_VERSION")
                        ),
                    )
                    .map_err(|e| Error(e.to_string()))?;
                    emit(
                        &mut output,
                        "param name=variant value=frisian type=enum values=frisian",
                    )
                    .map_err(|e| Error(e.to_string()))?;
                    emit(
                        &mut output,
                        "param name=tt-size value=16 type=int min=1 max=256",
                    )
                    .map_err(|e| Error(e.to_string()))?;
                    emit(&mut output, "wait").map_err(|e| Error(e.to_string()))?;
                }
                "set-param" => match (m.get("name"), m.get("value")) {
                    (Some("variant"), Some("frisian")) => {}
                    (Some("variant"), _) => {
                        return Err(Error("only frisian variant is supported".into()))
                    }
                    (Some("tt-size"), Some(value)) => {
                        let size = value.parse().map_err(|_| Error("invalid tt-size".into()))?;
                        limits = limits.with_tt_megabytes(size)?;
                    }
                    _ => {}
                },
                "init" => {
                    ready = true;
                    emit(&mut output, "ready").map_err(|e| Error(e.to_string()))?;
                }
                "ping" => {
                    emit(&mut output, "pong").map_err(|e| Error(e.to_string()))?;
                }
                "new-game" => {
                    game = Game::default();
                }
                "pos" => {
                    let position = if let Some(text) = m.get("pos") {
                        Position::from_hub(text)?
                    } else if m.has("start") {
                        Position::starting()
                    } else {
                        return Err(Error("pos requires pos= or start".into()));
                    };
                    let mut next = Game::new(position);
                    for text in m.get("moves").unwrap_or("").split_whitespace() {
                        let mv = next.position().parse_move(text)?;
                        next.play(&mv)?;
                    }
                    game = next; // Commit only after every replay move is valid.
                    limits = SearchLimits::default().with_tt_megabytes(limits.tt_megabytes())?;
                }
                "level" => {
                    if ["time", "inc", "moves", "move-time", "nodes", "infinite"]
                        .iter()
                        .any(|k| m.has(k))
                    {
                        return Err(Error("this stage supports level depth only".into()));
                    }
                    if let Some(depth) = m.get("depth") {
                        let depth = depth.parse().map_err(|_| Error("invalid depth".into()))?;
                        limits =
                            SearchLimits::new(depth)?.with_tt_megabytes(limits.tt_megabytes())?;
                    }
                }
                "go" => {
                    if !ready {
                        return Err(Error("init required before go".into()));
                    }
                    if !m.has("think") && !m.has("analyze") {
                        return Err(Error(
                            "use go think or go analyze; ponder is not yet supported".into(),
                        ));
                    }
                    let mut failure = None;
                    let result = search_with_reporter(&game, limits, |r| {
                        if failure.is_none() {
                            failure = emit(&mut output, &report(r)).err();
                        }
                    });
                    if let Some(e) = failure {
                        return Err(Error(e.to_string()));
                    }
                    let done = result
                        .best_move
                        .map_or_else(|| "done".to_owned(), |mv| format!("done move={mv}"));
                    emit(&mut output, &done).map_err(|e| Error(e.to_string()))?;
                }
                _ => {} // Unknown commands are ignored per Hub v2.
            }
            Ok(())
        })();
        if let Err(error) = result {
            emit(
                &mut output,
                &format!("error message={}", quoted(&error.to_string())),
            )?;
        }
        if line.trim() == "quit" {
            break;
        }
    }
    Ok(())
}
