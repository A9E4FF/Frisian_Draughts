//! Reproducible fixed-depth benchmark; run with --release.
use frisian_draughts::search::{search, SearchLimits};
use frisian_draughts::{Game, Piece, Position, Side, Square};
fn fixture(turn: Side, pieces: &[(u8, Side, Piece)]) -> Game {
    let pieces: Vec<_> = pieces
        .iter()
        .map(|&(n, s, p)| (Square::new(n).unwrap(), s, p))
        .collect();
    Game::new(Position::new(turn, &pieces, [None; 2]).unwrap())
}
fn main() {
    use Piece::{King, Man};
    use Side::{Black, White};
    let fixtures = [
        ("opening", Game::default()),
        ("tactical", {
            let mut pieces = Vec::new();
            for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15, 16] {
                pieces.push((n, Black, Man));
            }
            for n in [
                25, 27, 29, 35, 36, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
            ] {
                pieces.push((n, White, Man));
            }
            fixture(Black, &pieces)
        }),
        (
            "capture-combination",
            fixture(
                White,
                &[
                    (49, White, King),
                    (25, Black, King),
                    (7, Black, Man),
                    (30, Black, Man),
                    (19, Black, Man),
                    (46, Black, King),
                    (35, Black, Man),
                    (11, Black, Man),
                    (42, Black, King),
                    (15, Black, Man),
                    (34, Black, Man),
                ],
            ),
        ),
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
    ];
    let args: Vec<_> = std::env::args().skip(1).collect();
    println!("position,depth,completed_depth,nodes,quiescence_nodes,seconds,score,move");
    for (name, game) in fixtures {
        if args.first().is_some_and(|filter| filter != name) {
            continue;
        }
        for depth in [4, 6, 8, 10] {
            let r = search(&game, SearchLimits::new(depth).unwrap());
            println!(
                "{name},{depth},{},{},{},{:.6},{},{}",
                r.completed_depth,
                r.nodes,
                r.quiescence_nodes,
                r.elapsed.as_secs_f64(),
                r.score.map_or("unsearched".into(), |s| s.to_string()),
                r.best_move.map_or("none".into(), |mv| mv.to_string())
            );
        }
    }
}
