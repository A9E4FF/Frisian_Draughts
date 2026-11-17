//! Deterministic move-generation microbenchmark. Run with --release.
use frisian_draughts::{Game, Outcome, Piece, Position, Side, Square};
use std::{hint::black_box, time::Instant};
fn main() {
    let mut positions = Vec::new();
    let mut seed = 3101u64;
    for _ in 0..20 {
        let mut game = Game::default();
        for _ in 0..100 {
            if game.outcome() != Outcome::Ongoing {
                break;
            }
            positions.push(*game.position());
            let moves = game.position().legal_moves();
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            game.play(&moves[seed as usize % moves.len()]).unwrap();
        }
    }
    for (n, side) in [(1, Side::White), (5, Side::Black)] {
        let pieces = [
            (Square::new(n).unwrap(), side, Piece::King),
            (
                Square::new(if n == 1 { 20 } else { 31 }).unwrap(),
                side.other(),
                Piece::King,
            ),
        ];
        positions.push(Position::new(side, &pieces, [None; 2]).unwrap());
    }
    let start = Instant::now();
    let mut checksum = 0usize;
    let rounds = 100;
    for _ in 0..rounds {
        for p in &positions {
            checksum = checksum.wrapping_add(black_box(p).legal_moves().len());
        }
    }
    println!("positions,calls,moves,seconds");
    println!(
        "{},{},{},{:.6}",
        positions.len(),
        positions.len() * rounds,
        black_box(checksum),
        start.elapsed().as_secs_f64()
    );
}
