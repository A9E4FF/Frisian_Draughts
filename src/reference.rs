//! Original coordinate implementation, retained only as an independent test oracle.
use super::*;
use std::cell::Cell;
const DIAG: [(i8, i8); 4] = [(-1, -1), (-1, 1), (1, -1), (1, 1)];
const CAP_DIRS: [(i8, i8); 8] = [
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
    (-2, 0),
    (2, 0),
    (0, -2),
    (0, 2),
];
fn reference_squares(bits: u64) -> impl Iterator<Item = Square> {
    (1..=50).map(Square).filter(move |s| bits & s.bit() != 0)
}
thread_local! {static ENABLED:Cell<bool>=const {Cell::new(false)};}
pub(super) fn enabled() -> bool {
    ENABLED.with(Cell::get)
}
pub(super) fn with_reference<T>(f: impl FnOnce() -> T) -> T {
    struct Restore(bool);
    impl Drop for Restore {
        fn drop(&mut self) {
            ENABLED.with(|v| v.set(self.0));
        }
    }
    let _restore = Restore(ENABLED.with(|v| v.replace(true)));
    f()
}
impl Position {
    pub(super) fn legal_moves_reference(&self) -> Vec<Move> {
        let i = self.turn.index();
        let mut captures = Vec::new();
        for from in reference_squares(self.men[i] | self.kings[i]) {
            let king = self.kings[i] & from.bit() != 0;
            self.capture_rec_reference(from, from, king, 0, &mut captures);
        }
        let mut moves = if captures.is_empty() {
            let mut quiet = Vec::new();
            for from in reference_squares(self.men[i] | self.kings[i]) {
                let king = self.kings[i] & from.bit() != 0;
                if king && self.restrictions[i].is_some_and(|r| r.square == from && r.count == 3) {
                    continue;
                }
                for d in DIAG {
                    if !king && d.0 != if self.turn == Side::White { -1 } else { 1 } {
                        continue;
                    }
                    let mut next = from.step(d);
                    while let Some(to) = next {
                        if self.occupied() & to.bit() != 0 {
                            break;
                        }
                        quiet.push(Move {
                            from,
                            to,
                            captured: 0,
                        });
                        if !king {
                            break;
                        }
                        next = to.step(d);
                    }
                }
            }
            quiet
        } else {
            let score = |m: &Move| {
                let j = self.turn.other().index();
                64 * (m.captured & self.men[j]).count_ones()
                    + 126 * (m.captured & self.kings[j]).count_ones()
                    + u32::from(self.kings[i] & m.from.bit() != 0)
            };
            let best = captures.iter().map(&score).max().unwrap();
            captures.retain(|m| score(m) == best);
            captures
        };
        moves.sort_by_key(|m| (m.from, m.to, m.captured()));
        moves.dedup();
        moves
    }
    fn capture_rec_reference(
        &self,
        start: Square,
        from: Square,
        king: bool,
        captured: u64,
        out: &mut Vec<Move>,
    ) {
        // Jumped pieces remain blockers until the complete move ends.
        let blockers = self.occupied() & !start.bit();
        let enemy = (self.men[self.turn.other().index()] | self.kings[self.turn.other().index()])
            & !captured;
        let mut extended = false;
        for d in CAP_DIRS {
            let mut next = from.step(d);
            while let Some(jump) = next {
                if blockers & jump.bit() != 0 {
                    if enemy & jump.bit() != 0 {
                        let mut land = jump.step(d);
                        while let Some(to) = land {
                            if blockers & to.bit() != 0 {
                                break;
                            }
                            extended = true;
                            self.capture_rec_reference(start, to, king, captured | jump.bit(), out);
                            if !king {
                                break;
                            }
                            land = to.step(d);
                        }
                    }
                    break;
                }
                if !king {
                    break;
                }
                next = jump.step(d);
            }
        }
        if !extended && captured != 0 {
            out.push(Move {
                from: start,
                to: from,
                captured,
            });
        }
    }
}

pub(super) fn evaluate(p: &Position) -> i32 {
    let mut white = 0;
    for side in [Side::White, Side::Black] {
        let i = side.index();
        let mut value = p.men[i].count_ones() as i32 * 100 + p.kings[i].count_ones() as i32 * 300;
        for sq in reference_squares(p.men[i]) {
            let (_, file) = sq.coords();
            value += match file.min(9 - file) {
                0 => 8,
                1 => 4,
                _ => 0,
            };
        }
        if let Some(r) = p.restrictions[i] {
            value -= [0, 2, 6, 12][r.count as usize];
        }
        white += if side == Side::White { value } else { -value };
    }
    if p.turn == Side::White {
        white
    } else {
        -white
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::search::{search, SearchLimits};
    fn compare(p: Position) {
        let fast = p.legal_moves();
        let reference = p.legal_moves_reference();
        assert_eq!(fast, reference, "{p:?}");
        assert_eq!(crate::search::evaluate(&p), evaluate(&p));
        for mv in &fast {
            let mut checked = p;
            with_reference(|| checked.apply(mv)).unwrap();
            assert_eq!(p.successor(mv), checked);
        }
    }
    fn position(turn: Side, pieces: &[(u8, Side, Piece)]) -> Position {
        Position::new(
            turn,
            &pieces
                .iter()
                .map(|&(n, s, p)| (Square::new(n).unwrap(), s, p))
                .collect::<Vec<_>>(),
            [None; 2],
        )
        .unwrap()
    }
    #[test]
    fn tactical_edge_cases_and_restriction_states_match_reference() {
        use Piece::{King, Man};
        use Side::{Black, White};
        let fixtures = [
            position(
                White,
                &[
                    (28, White, Man),
                    (27, Black, Man),
                    (16, Black, Man),
                    (23, Black, King),
                ],
            ),
            position(White, &[(11, White, Man), (7, Black, Man), (8, Black, Man)]),
            position(
                White,
                &[(28, White, King), (23, Black, Man), (32, Black, Man)],
            ),
            position(
                White,
                &[
                    (45, White, King),
                    (8, Black, King),
                    (44, Black, King),
                    (12, Black, King),
                    (33, Black, King),
                    (18, Black, King),
                    (40, Black, King),
                ],
            ),
            position(
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
            position(
                White,
                &[
                    (28, White, King),
                    (46, White, Man),
                    (5, Black, King),
                    (1, Black, Man),
                ],
            ),
        ];
        for p in fixtures {
            compare(p);
        }
        for count in 1..=3 {
            let mut p = fixtures[5];
            p.restrictions[0] = Some(KingRestriction::new(Square(28), count).unwrap());
            p.restrictions[1] = Some(KingRestriction::new(Square(5), count).unwrap());
            compare(p);
            let mut q = p;
            q.turn = Black;
            compare(q);
        }
    }
    #[test]
    fn thousands_of_mixed_states_and_playouts_match_reference() {
        let mut seed = 3101u64;
        let mut random = || {
            seed = seed
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            seed
        };
        for _ in 0..500 {
            let mut pieces = Vec::new();
            for n in 1..=50 {
                let draw = random() >> 32;
                if draw % 5 != 0 {
                    continue;
                }
                let side = if draw & 8 == 0 {
                    Side::White
                } else {
                    Side::Black
                };
                let pc = if draw & 16 == 0
                    || (side == Side::White && n <= 5)
                    || (side == Side::Black && n >= 46)
                {
                    Piece::King
                } else {
                    Piece::Man
                };
                pieces.push((Square(n), side, pc));
            }
            let side = if random() >> 63 == 0 {
                Side::White
            } else {
                Side::Black
            };
            let p = Position::new(side, &pieces, [None; 2]).unwrap();
            compare(p);
            // Exercise counters even on quiet positions rarely reached by playouts.
            for side in [Side::White, Side::Black] {
                let i = side.index();
                if p.men[i] != 0 {
                    if let Some(king) = reference_squares(p.kings[i]).next() {
                        for count in 1..=3 {
                            let mut q = p;
                            q.restrictions[i] = Some(KingRestriction::new(king, count).unwrap());
                            compare(q);
                        }
                    }
                }
            }
        }
        for _ in 0..40 {
            let mut game = Game::default();
            for _ in 0..150 {
                compare(*game.position());
                if game.outcome() != Outcome::Ongoing {
                    break;
                }
                let moves = game.position().legal_moves();
                game.play(&moves[(random() >> 32) as usize % moves.len()])
                    .unwrap();
            }
        }
    }
    #[test]
    fn search_matches_original_generator_and_evaluator() {
        let mut game = Game::default();
        let mut seed = 113u64;
        for sample in 0..16 {
            if game.outcome() != Outcome::Ongoing {
                break;
            }
            let depth = if sample < 4 { 4 } else { 2 };
            let limits = SearchLimits::new(depth).unwrap();
            let fast = search(&game, limits);
            let old = with_reference(|| search(&game, limits));
            assert_eq!(fast.best_move, old.best_move);
            assert_eq!(fast.score, old.score);
            assert_eq!(fast.principal_variation, old.principal_variation);
            assert_eq!(fast.nodes, old.nodes);
            assert_eq!(fast.quiescence_nodes, old.quiescence_nodes);
            assert_eq!(fast.completed_depth, old.completed_depth);
            let moves = game.position().legal_moves();
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            game.play(&moves[seed as usize % moves.len()]).unwrap();
        }
    }
}
