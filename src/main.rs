mod analysis;
use frisian_draughts::search::{search, SearchLimits};
use frisian_draughts::{Game, Outcome, Side};
use std::io::{self, Write};

fn engine(game: &mut Game, limits: SearchLimits) {
    let result = search(game, limits);
    if let Some(mv) = &result.best_move {
        println!("Engine: {mv}");
        if let Some(score) = result.score {
            println!(
                "Depth {} | score {score:+} | nodes {} (quiescence {}) | {:.3}s | PV {}",
                result.completed_depth,
                result.nodes,
                result.quiescence_nodes,
                result.elapsed.as_secs_f64(),
                result
                    .principal_variation
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(" ")
            );
        } else {
            println!("Only legal move — immediate selection (not searched)");
        }
        game.play(mv).expect("selected legal move");
    }
}
fn main() -> io::Result<()> {
    if std::env::args().nth(1).as_deref() == Some("--analysis-json") {
        return analysis::run(io::stdin().lock(), io::stdout().lock());
    }
    let mut game = Game::default();
    let mut checkpoints = Vec::new();
    let mut limits = SearchLimits::default();
    println!(
        "Frisian Draughts — you are White. Search depth 10. Type help for commands.\n{}",
        game.position()
    );
    loop {
        print!("> ");
        io::stdout().flush()?;
        let mut input = String::new();
        if io::stdin().read_line(&mut input)? == 0 {
            break;
        }
        let input = input.trim();
        match input {
            "quit" => break,
            "help" => println!("board | moves | play <move> | go | depth <1–64> | undo | new | quit\nMoves: 32-28 or 32x23; ambiguous captures need the displayed captured-square suffix.\nw/b: men, W/B: kings. Engine plays Black automatically. Fixed-depth alpha-beta with capture quiescence; no time limit."),
            "board" => println!("{}", game.position()),
            "moves" => println!("{}", game.position().legal_moves().iter().map(ToString::to_string).collect::<Vec<_>>().join(" ")),
            "new" => { game = Game::default(); checkpoints.clear(); println!("{}", game.position()); }
            "undo" => {
                if let Some(ply) = checkpoints.pop() { game.undo_to(ply).unwrap(); println!("{}", game.position()); }
                else { println!("Nothing to undo"); }
            }
            "go" => {
                if game.outcome() == Outcome::Ongoing { checkpoints.push(game.ply()); engine(&mut game, limits); println!("{}", game.position()); }
            }
            _ => {
                if input == "depth" || input.starts_with("depth ") {
                    match input.strip_prefix("depth ").and_then(|s| s.parse::<u8>().ok()).and_then(|d| SearchLimits::new(d).ok()) {
                        Some(next) => { limits = next; println!("Search depth: {}", limits.max_depth()); }
                        None => println!("Error: depth must be 1–64 (still {})", limits.max_depth()),
                    }
                } else if let Some(text) = input.strip_prefix("play ") {
                    let ply = game.ply();
                    match game.position().parse_move(text).and_then(|mv| game.play(&mv)) {
                        Ok(()) => {
                            checkpoints.push(ply);
                            if game.position().turn() == Side::Black { engine(&mut game, limits); }
                            println!("{}", game.position());
                        }
                        Err(e) => println!("Error: {e}"),
                    }
                } else { println!("Unknown command; type help"); }
            }
        }
        match game.outcome() {
            Outcome::Ongoing => {}
            Outcome::Won(side) => println!("{side:?} wins"),
            Outcome::Draw => println!("Draw by threefold repetition"),
        }
    }
    Ok(())
}
