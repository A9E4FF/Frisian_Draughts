//! TT-on/off comparison; run with --release. Scores must agree; tied moves may differ.
use frisian_draughts::search::{search, SearchLimits};
use frisian_draughts::{Game, Piece, Position, Side, Square};
fn main() {
    use Piece::{King, Man};
    use Side::{Black, White};
    let fixture = |turn, pieces: &[(u8, Side, Piece)]| {
        Game::new(
            Position::new(
                turn,
                &pieces
                    .iter()
                    .map(|&(n, s, p)| (Square::new(n).unwrap(), s, p))
                    .collect::<Vec<_>>(),
                [None; 2],
            )
            .unwrap(),
        )
    };
    let mut tactical = Vec::new();
    for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15, 16] {
        tactical.push((n, Black, Man));
    }
    for n in [
        25, 27, 29, 35, 36, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
    ] {
        tactical.push((n, White, Man));
    }
    println!("position,depth,tt,nodes,qnodes,seconds,probes,hits,cutoffs,score,move");
    for (name, game) in [
        ("opening", Game::default()),
        ("tactical", fixture(Black, &tactical)),
        (
            "kings",
            fixture(
                White,
                &[
                    (1, White, King),
                    (46, White, Man),
                    (5, Black, King),
                    (20, Black, Man),
                ],
            ),
        ),
    ] {
        for depth in [4, 6, 8, 10] {
            let mut previous = None;
            for enabled in [false, true] {
                let r = search(
                    &game,
                    SearchLimits::new(depth).unwrap().with_tt_enabled(enabled),
                );
                if let Some(score) = previous {
                    assert_eq!(Some(score), r.score, "{name}, depth {depth}");
                }
                previous = r.score;
                let mut replay = game.clone();
                for mv in &r.principal_variation {
                    replay.play(mv).unwrap();
                }
                println!(
                    "{name},{depth},{enabled},{},{},{:.6},{},{},{},{},{}",
                    r.nodes,
                    r.quiescence_nodes,
                    r.elapsed.as_secs_f64(),
                    r.tt_probes,
                    r.tt_hits,
                    r.tt_cutoffs,
                    r.score.unwrap(),
                    r.best_move.unwrap()
                );
            }
        }
    }
}
