//! Line-delimited JSON bridge for the Python position suite.
use frisian_draughts::search::{search_with_reporter, SearchLimits, SearchResult, SearchStatus};
use frisian_draughts::{Game, KingRestriction, Outcome, Piece, Position, Side, Square};
use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};
use std::time::Duration;

#[derive(Deserialize)]
struct Request {
    #[serde(default = "default_command")]
    command: String,
    fen: String,
    #[serde(default = "default_depth")]
    depth: u8,
    #[serde(default)]
    accepted_moves: Vec<String>,
    #[serde(default)]
    restrictions: Option<Restrictions>,
    #[serde(default)]
    moves: Vec<String>,
    #[serde(default = "default_tt")]
    tt_enabled: bool,
    #[serde(default = "default_memory")]
    tt_megabytes: usize,
    #[serde(default)]
    search_forced_root: bool,
    #[serde(default)]
    time_limit_ms: Option<u64>,
}
fn default_command() -> String {
    "analyze".into()
}
fn default_depth() -> u8 {
    10
}
fn default_tt() -> bool {
    true
}
fn default_memory() -> usize {
    16
}
#[derive(Deserialize, Default)]
#[serde(deny_unknown_fields)]
struct Restrictions {
    #[serde(default)]
    white: Option<Restriction>,
    #[serde(default)]
    black: Option<Restriction>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Restriction {
    square: u8,
    count: u8,
}
fn side_name(side: Side) -> &'static str {
    if side == Side::White {
        "white"
    } else {
        "black"
    }
}
fn restriction_json(position: &Position, side: Side) -> Value {
    position.restriction(side).map_or(
        Value::Null,
        |r| json!({"square":r.square().number(),"count":r.count()}),
    )
}
fn emit(out: &mut impl Write, event: &Value) -> io::Result<()> {
    serde_json::to_writer(&mut *out, event)?;
    writeln!(out)?;
    out.flush()
}
fn result_event(kind: &str, r: &SearchResult, accepted: &[String]) -> Value {
    let best = r.best_move.as_ref().map(ToString::to_string);
    let passed = if accepted.is_empty() {
        None
    } else {
        Some(best.as_ref().is_some_and(|s| accepted.contains(s)))
    };
    let status = match r.status {
        SearchStatus::Completed => "completed",
        SearchStatus::Terminal => "terminal",
        SearchStatus::ForcedMove => "forced_move",
        SearchStatus::Cancelled => "cancelled",
        SearchStatus::NodeLimit => "node_limit",
        SearchStatus::TimeLimit => "time_limit",
    };
    json!({"type":kind,"status":status,"tt_capacity":r.tt_capacity,
        "tt_storage_budget_bytes":r.tt_storage_budget_bytes,"depth":r.completed_depth,"score":r.score,"best_move":best,
        "pv":r.principal_variation.iter().map(ToString::to_string).collect::<Vec<_>>(),
        "nodes":r.nodes,"quiescence_nodes":r.quiescence_nodes,"elapsed_ms":r.elapsed.as_secs_f64()*1000.0,
        "tt_probes":r.tt_probes,"tt_hits":r.tt_hits,"tt_cutoffs":r.tt_cutoffs,"passed":passed})
}
fn handle(request: Request, out: &mut impl Write) -> Result<(), String> {
    if !["inspect", "analyze"].contains(&request.command.as_str()) {
        return Err("command must be inspect or analyze".into());
    }
    let mut limits = SearchLimits::new(request.depth)
        .and_then(|l| l.with_tt_megabytes(request.tt_megabytes))
        .map_err(|e| e.to_string())?
        .with_tt_enabled(request.tt_enabled)
        .with_forced_root_search(request.search_forced_root);
    if let Some(ms) = request.time_limit_ms {
        limits = limits.with_max_time(Duration::from_millis(ms));
    }
    let mut position = Position::from_fen(&request.fen).map_err(|e| e.to_string())?;
    if let Some(restrictions) = request.restrictions {
        let parse = |r: Option<Restriction>| -> Result<Option<KingRestriction>, String> {
            r.map(|r| {
                Square::new(r.square)
                    .and_then(|sq| KingRestriction::new(sq, r.count))
                    .map_err(|e| e.to_string())
            })
            .transpose()
        };
        let states = [parse(restrictions.white)?, parse(restrictions.black)?];
        let pieces: Vec<_> = (1..=50)
            .filter_map(|n| {
                let sq = Square::new(n).unwrap();
                position.piece_at(sq).map(|(side, pc)| (sq, side, pc))
            })
            .collect();
        position = Position::new(position.turn(), &pieces, states).map_err(|e| e.to_string())?;
    }
    let mut game = Game::new(position);
    for text in request.moves {
        let mv = game
            .position()
            .parse_move(&text)
            .map_err(|e| format!("replay move {text}: {e}"))?;
        game.play(&mv)
            .map_err(|e| format!("replay move {text}: {e}"))?;
    }
    let position = game.position();
    let mut accepted = Vec::new();
    for text in request.accepted_moves {
        let mv = position
            .parse_move(&text)
            .map_err(|e| format!("accepted move {text}: {e}"))?
            .to_string();
        if !accepted.contains(&mv) {
            accepted.push(mv);
        }
    }
    let pieces:Vec<_>=(1..=50).filter_map(|n|{
        let sq=Square::new(n).unwrap();position.piece_at(sq).map(|(side,pc)|
            json!({"square":n,"side":side_name(side),"piece":if pc==Piece::Man {"man"}else{"king"}}))
    }).collect();
    let outcome = match game.outcome() {
        Outcome::Ongoing => "ongoing",
        Outcome::Draw => "draw",
        Outcome::Won(Side::White) => "white-win",
        Outcome::Won(Side::Black) => "black-win",
    };
    emit(out,&json!({"type":"loaded","fen":position.to_fen(),"hub":position.to_hub(),"outcome":outcome,"turn":side_name(position.turn()),
        "pieces":pieces,"restrictions":{"white":restriction_json(position,Side::White),"black":restriction_json(position,Side::Black)},
        "legal_moves":position.legal_moves().iter().map(ToString::to_string).collect::<Vec<_>>(),
        "accepted_moves":accepted,"warnings":["FEN has no earlier repetition history; king restrictions start at zero unless supplied. Replay contains history only from the imported position onward."]}))
        .map_err(|e|e.to_string())?;
    if request.command == "inspect" {
        return Ok(());
    }
    let mut write_error = None;
    let result = search_with_reporter(&game, limits, |r| {
        if write_error.is_none() {
            if let Err(e) = emit(out, &result_event("iteration", r, &accepted)) {
                write_error = Some(e.to_string());
            }
        }
    });
    if let Some(error) = write_error {
        return Err(error);
    }
    emit(out, &result_event("result", &result, &accepted)).map_err(|e| e.to_string())
}
/// Process independent requests; malformed input produces an error event, never UI prose.
pub fn run(input: impl BufRead, mut output: impl Write) -> io::Result<()> {
    for line in input.lines() {
        let line = line?;
        let result = serde_json::from_str::<Request>(&line)
            .map_err(|e| format!("invalid request: {e}"))
            .and_then(|request| handle(request, &mut output));
        if let Err(message) = result {
            emit(&mut output, &json!({"type":"error","message":message}))?;
        }
    }
    Ok(())
}
