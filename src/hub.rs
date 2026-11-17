//! Hub v2 adapter. Protocol reference: Scan 3.1, Fabien Letouzey; GPL-3.0-only.
//! Search runs in a worker with cooperative limits and responsive command input.
use crate::search::{search_with_control, SearchControl, SearchLimits, SearchResult};
use crate::{Error, Game, KingRestriction, Piece, Position, Side, Square};
use std::io::{self, BufRead, Write};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

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
    if line
        .trim_end_matches(['\r', '\n'])
        .chars()
        .any(|c| c.is_control() && c != '\t')
    {
        return Err(Error("control character in Hub message".into()));
    }
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

fn line(out: &Mutex<impl Write>, text: &str) -> Result<(), Error> {
    emit(&mut *out.lock().unwrap(), text).map_err(|e| Error(e.to_string()))
}

fn seconds(text: &str) -> Result<f64, Error> {
    let n: f64 = text.parse().map_err(|_| Error("invalid time".into()))?;
    if !n.is_finite() || n < 0.0 {
        return Err(Error("time must be finite and nonnegative".into()));
    }
    Ok(n)
}
fn level(m: &Message, memory: usize) -> Result<(SearchLimits, Option<Duration>), Error> {
    let depth = m
        .get("depth")
        .unwrap_or("64")
        .parse()
        .map_err(|_| Error("invalid depth".into()))?;
    let mut limits = SearchLimits::new(depth)?.with_tt_megabytes(memory)?;
    if let Some(nodes) = m.get("nodes") {
        limits =
            limits.with_max_nodes(nodes.parse().map_err(|_| Error("invalid nodes".into()))?)?;
    }
    let duration = if let Some(t) = m.get("move-time") {
        Some(seconds(t)?)
    } else if let Some(t) = m.get("time") {
        let available = seconds(t)? + seconds(m.get("inc").unwrap_or("0"))?;
        let moves: u32 = m
            .get("moves")
            .unwrap_or("30")
            .parse()
            .map_err(|_| Error("invalid remaining moves".into()))?;
        if moves == 0 {
            return Err(Error("remaining moves must be positive".into()));
        }
        Some((available / f64::from(moves) * 0.95).min(available))
    } else {
        None
    };
    let duration = duration
        .map(Duration::try_from_secs_f64)
        .transpose()
        .map_err(|_| Error("time out of range".into()))?;
    Ok((limits, duration))
}

/// Read commands on the owner thread while one scoped worker searches.
/// Every search has its own control and TT; no old result can cross stop/join.
pub fn run(input: impl BufRead, output: impl Write + Send) -> io::Result<()> {
    let output = Mutex::new(output);
    thread::scope(|scope| -> Result<(), Error> {
        struct StopOnDrop(Option<SearchControl>);
        impl Drop for StopOnDrop {
            fn drop(&mut self) {
                if let Some(c) = &self.0 {
                    c.stop();
                }
            }
        }
        let mut shutdown = StopOnDrop(None);
        let mut game = Game::default();
        let mut memory = 16;
        let mut tt_enabled = true;
        let mut limits = SearchLimits::default();
        let mut duration = None;
        let mut ready = false;
        type Active<'scope> = (
            SearchControl,
            thread::ScopedJoinHandle<'scope, Result<(), Error>>,
            Option<Duration>,
        );
        let mut active: Option<Active<'_>> = None;
        for raw in input.lines() {
            let raw = raw.map_err(|e| Error(e.to_string()))?;
            if raw.trim().is_empty() {
                continue;
            }
            if active
                .as_ref()
                .is_some_and(|(c, h, _)| c.is_stopped() || h.is_finished())
            {
                let (_, handle, _) = active.take().unwrap();
                handle
                    .join()
                    .map_err(|_| Error("search worker panicked".into()))??;
            }
            let result = (|| -> Result<bool, Error> {
                let m = parse(&raw)?;
                if m.command == "quit" {
                    return Ok(true);
                }
                if active.is_some()
                    && ["pos", "level", "go", "new-game", "init", "set-param"]
                        .contains(&m.command.as_str())
                {
                    return Err(Error("stop active search before changing state".into()));
                }
                match m.command.as_str() {
                    "hub" => {
                        line(
                            &output,
                            &format!(
                                "id name=Frisian-Draughts version={} author=Contributors extensions=frisian-state-v1",
                                env!("CARGO_PKG_VERSION")
                            ),
                        )?;
                        line(
                            &output,
                            "param name=variant value=frisian type=enum values=frisian",
                        )?;
                        line(
                            &output,
                            "param name=tt-size value=16 type=int min=1 max=256",
                        )?;
                        line(&output, "param name=tt-enabled value=true type=bool")?;
                        line(&output, "wait")?;
                    }
                    "set-param" => match (m.get("name"), m.get("value")) {
                        (Some("variant"), Some("frisian")) => {}
                        (Some("variant"), _) => {
                            return Err(Error("only frisian variant is supported".into()))
                        }
                        (Some("tt-size"), Some(v)) => {
                            let size = v.parse().map_err(|_| Error("invalid tt-size".into()))?;
                            limits = limits.with_tt_megabytes(size)?;
                            memory = size;
                        }
                        (Some("tt-enabled"), Some(v)) => {
                            tt_enabled = v.parse().map_err(|_| Error("tt-enabled must be true or false".into()))?;
                            limits = limits.with_tt_enabled(tt_enabled);
                        }
                        _ => {}
                    },
                    "init" => {
                        ready = true;
                        line(&output, "ready")?;
                    }
                    "ping" => line(&output, "pong")?,
                    "stop" => {
                        if let Some((control, handle, _)) = active.take() {
                            control.stop();
                            handle
                                .join()
                                .map_err(|_| Error("search worker panicked".into()))??;
                        }
                    }
                    "ponder-hit" => {
                        if let Some((control, _, Some(budget))) = &active {
                            control.set_time_limit(*budget);
                        }
                    }
                    "new-game" => {
                        game = Game::default();
                    }
                    "pos" => {
                        let mut p = if let Some(v) = m.get("pos") {
                            Position::from_hub(v)?
                        } else if m.has("start") {
                            Position::starting()
                        } else {
                            return Err(Error("pos requires pos= or start".into()));
                        };
                        if let Some(state) = m.get("frisian-state") {
                            let fields: Vec<_> = state.split(',').collect();
                            if fields.len() != 2 { return Err(Error("frisian-state requires white,black square:count".into())); }
                            let mut restrictions = [None; 2];
                            for (i, field) in fields.iter().enumerate() {
                                let (square, count) = field.split_once(':').ok_or_else(|| Error("invalid restriction state".into()))?;
                                if *field != "0:0" {
                                    let square = square.parse().map_err(|_| Error("invalid restriction square".into()))?;
                                    let count = count.parse().map_err(|_| Error("invalid restriction count".into()))?;
                                    restrictions[i] = Some(KingRestriction::new(Square::new(square)?, count)?);
                                }
                            }
                            let pieces: Vec<_> = (1..=50).filter_map(|n| {
                                let sq = Square::new(n).unwrap(); p.piece_at(sq).map(|(s, pc)| (sq, s, pc))
                            }).collect();
                            p = Position::new(p.turn(), &pieces, restrictions)?;
                        }
                        let mut next = Game::new(p);
                        for text in m.get("moves").unwrap_or("").split_whitespace() {
                            let mv = next.position().parse_move(text)?;
                            next.play(&mv)?;
                        }
                        game = next;
                        limits = SearchLimits::default().with_tt_megabytes(memory)?.with_tt_enabled(tt_enabled);
                        duration = None;
                    }
                    "level" => {
                        let next = level(&m, memory)?;
                        limits = next.0.with_tt_enabled(tt_enabled);
                        duration = next.1;
                    }
                    "go" => {
                        if !ready {
                            return Err(Error("init required before go".into()));
                        }
                        if !["think", "analyze", "ponder"].iter().any(|k| m.has(k)) {
                            return Err(Error("go requires think, analyze or ponder".into()));
                        }
                        let control = SearchControl::default();
                        if !m.has("ponder") {
                            if let Some(d) = duration {
                                control.set_time_limit(d);
                            }
                        }
                        let worker_control = control.clone();
                        shutdown.0 = Some(control.clone());
                        let root = game.clone();
                        let out = &output;
                        let search_limits = limits;
                        let handle = scope.spawn(move || {
                            let mut failure = None;
                            let result = search_with_control(
                                &root,
                                search_limits,
                                worker_control.clone(),
                                |r| {
                                    if failure.is_none() {
                                        failure = line(out, &report(r)).err();
                                    }
                                    if failure.is_some() {
                                        worker_control.stop();
                                    }
                                },
                            );
                            if let Some(e) = failure {
                                return Err(e);
                            }
                            worker_control.stop(); // Mark completion before publishing done.
                            let done = result
                                .best_move
                                .map_or_else(|| "done".to_owned(), |mv| format!("done move={mv}"));
                            line(out, &done)
                        });
                        active = Some((
                            control,
                            handle,
                            if m.has("ponder") { duration } else { None },
                        ));
                        limits = SearchLimits::default().with_tt_megabytes(memory)?.with_tt_enabled(tt_enabled);
                        duration = None;
                    }
                    _ => {}
                }
                Ok(false)
            })();
            match result {
                Ok(true) => break,
                Err(e) => line(
                    &output,
                    &format!("error message={}", quoted(&e.to_string())),
                )?,
                Ok(false) => {}
            }
        }
        if let Some((control, handle, _)) = active {
            control.stop();
            handle
                .join()
                .map_err(|_| Error("search worker panicked".into()))??;
        }
        Ok(())
    })
    .map_err(|e| io::Error::other(e.to_string()))
}
