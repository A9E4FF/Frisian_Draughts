//! Bounded, single-threaded transposition storage. GPL-3.0-only.
//! Scores are reusable only with a clean repetition context and equal depth.
use crate::{Move, Position, Side};
use std::mem::size_of;

const CLUSTER: usize = 4;
const MAX_PV: usize = 128;
const MATE_THRESHOLD: i32 = 20_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Bound {
    Exact,
    Lower,
    Upper,
}

struct Entry {
    key: u64,
    position: Position,
    depth: u8,
    score: i32,
    bound: Bound,
    clean: bool,
    generation: u8,
    pv: Box<[Move]>,
}

pub(crate) struct Lookup {
    pub hit: bool,
    pub best_move: Option<Move>,
    pub cutoff: Option<(i32, Vec<Move>)>,
}

pub(crate) struct Table {
    slots: Vec<Option<Entry>>,
    mask: usize,
    generation: u8,
}
impl Table {
    pub fn new(megabytes: usize) -> Self {
        // Reserve worst-case boxed PV bytes as well as slot metadata. This
        // deliberately trades capacity for a strict allocation upper bound.
        let maximum_entry = size_of::<Option<Entry>>() + MAX_PV * size_of::<Move>();
        let clusters = (megabytes * 1024 * 1024 / (CLUSTER * maximum_entry)).max(1);
        let clusters = 1usize << (usize::BITS - 1 - clusters.leading_zeros());
        let slots = std::iter::repeat_with(|| None)
            .take(clusters * CLUSTER)
            .collect();
        Self {
            slots,
            mask: clusters - 1,
            generation: 0,
        }
    }
    pub fn capacity(&self) -> usize {
        self.slots.len()
    }
    pub fn storage_budget_bytes(&self) -> usize {
        self.slots.capacity() * (size_of::<Option<Entry>>() + MAX_PV * size_of::<Move>())
    }
    pub fn start_iteration(&mut self, generation: u8) {
        self.generation = generation;
    }
    fn cluster(&self, key: u64) -> usize {
        (key as usize & self.mask) * CLUSTER
    }
    pub fn lookup(
        &self,
        position: Position,
        depth: u8,
        clean: bool,
        ply: u16,
        alpha: i32,
        beta: i32,
    ) -> Lookup {
        self.lookup_key(key(&position), position, depth, clean, ply, alpha, beta)
    }
    #[allow(clippy::too_many_arguments)]
    fn lookup_key(
        &self,
        key: u64,
        position: Position,
        depth: u8,
        clean: bool,
        ply: u16,
        alpha: i32,
        beta: i32,
    ) -> Lookup {
        let start = self.cluster(key);
        let mut result = Lookup {
            hit: false,
            best_move: None,
            cutoff: None,
        };
        let mut ordering_depth = 0;
        for entry in self.slots[start..start + CLUSTER].iter().flatten() {
            // A matching lock/hash never substitutes for full-position equality.
            if entry.key != key || entry.position != position {
                continue;
            }
            result.hit = true;
            if result.best_move.is_none() || entry.depth > ordering_depth {
                result.best_move = entry.pv.first().cloned();
                ordering_depth = entry.depth;
            }
            if !clean || !entry.clean || entry.depth != depth {
                continue;
            }
            let score = from_table(entry.score, ply);
            if entry.bound == Bound::Exact
                || (entry.bound == Bound::Lower && score >= beta)
                || (entry.bound == Bound::Upper && score <= alpha)
            {
                result.cutoff = Some((score, entry.pv.to_vec()));
                break;
            }
        }
        result
    }
    #[allow(clippy::too_many_arguments)]
    pub fn store(
        &mut self,
        position: Position,
        depth: u8,
        clean: bool,
        ply: u16,
        score: i32,
        bound: Bound,
        pv: &[Move],
    ) {
        self.store_key(
            key(&position),
            position,
            depth,
            clean,
            ply,
            score,
            bound,
            pv,
        );
    }
    #[allow(clippy::too_many_arguments)]
    fn store_key(
        &mut self,
        key: u64,
        position: Position,
        depth: u8,
        clean: bool,
        ply: u16,
        score: i32,
        bound: Bound,
        pv: &[Move],
    ) {
        if pv.is_empty() || pv.len() > MAX_PV {
            return;
        }
        let start = self.cluster(key);
        let cluster = &self.slots[start..start + CLUSTER];
        let replacement = cluster
            .iter()
            .position(|slot| {
                slot.as_ref().is_some_and(|e| {
                    e.key == key && e.position == position && e.depth == depth && e.clean == clean
                })
            })
            .or_else(|| cluster.iter().position(Option::is_none))
            .unwrap_or_else(|| {
                cluster
                    .iter()
                    .enumerate()
                    .min_by_key(|(_, slot)| {
                        let e = slot.as_ref().unwrap();
                        (e.generation == self.generation, e.depth)
                    })
                    .unwrap()
                    .0
            });
        self.slots[start + replacement] = Some(Entry {
            key,
            position,
            depth,
            clean,
            score: to_table(score, ply),
            bound,
            generation: self.generation,
            pv: pv.to_vec().into_boxed_slice(),
        });
    }
}

/// Root-relative terminal scores become position-relative in storage.
fn to_table(score: i32, ply: u16) -> i32 {
    if score >= MATE_THRESHOLD {
        score + i32::from(ply)
    } else if score <= -MATE_THRESHOLD {
        score - i32::from(ply)
    } else {
        score
    }
}
fn from_table(score: i32, ply: u16) -> i32 {
    if score >= MATE_THRESHOLD {
        score - i32::from(ply)
    } else if score <= -MATE_THRESHOLD {
        score + i32::from(ply)
    } else {
        score
    }
}
fn random(mut state: u64) -> u64 {
    state = state.wrapping_add(0x9e3779b97f4a7c15);
    state = (state ^ (state >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    state = (state ^ (state >> 27)).wrapping_mul(0x94d049bb133111eb);
    state ^ (state >> 31)
}
/// Deterministic Zobrist key: every piece, turn, and active king restriction.
/// Full Position equality is still verified when probing.
pub(crate) fn key(position: &Position) -> u64 {
    let mut key = if position.turn == Side::Black {
        random(256)
    } else {
        0
    };
    for side in 0..2 {
        for (kind, mut bits) in [position.men[side], position.kings[side]]
            .into_iter()
            .enumerate()
        {
            while bits != 0 {
                let square = bits.trailing_zeros();
                bits &= bits - 1;
                key ^= random((side * 128 + kind * 64) as u64 + u64::from(square));
            }
        }
        if let Some(r) = position.restrictions[side] {
            key ^= random(257 + (side * 256 + usize::from(r.count) * 64 + r.square.index()) as u64);
        }
    }
    key
}

/// Only a new root or the first position after an irreversible conversion has
/// no relevant predecessor repetition states. Elsewhere entries order moves only.
pub(crate) fn clean_history(history: &[Position]) -> bool {
    if history.len() <= 1 {
        return true;
    }
    let last = history[history.len() - 1];
    let previous = history[history.len() - 2];
    previous.men != last.men || previous.occupied().count_ones() != last.occupied().count_ones()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{KingRestriction, Piece, Square};
    fn position() -> Position {
        Position::new(
            Side::White,
            &[
                (Square::new(28).unwrap(), Side::White, Piece::King),
                (Square::new(46).unwrap(), Side::White, Piece::Man),
                (Square::new(1).unwrap(), Side::Black, Piece::Man),
            ],
            [None; 2],
        )
        .unwrap()
    }
    #[test]
    fn zobrist_includes_all_state_and_is_deterministic() {
        let p = position();
        assert_eq!(key(&p), key(&p));
        let mut q = p;
        q.turn = Side::Black;
        assert_ne!(key(&p), key(&q));
        for count in 1..=3 {
            q = p;
            q.restrictions[0] =
                Some(KingRestriction::new(Square::new(28).unwrap(), count).unwrap());
            assert_ne!(key(&p), key(&q));
        }
        q = p.successor(&p.parse_move("46-41").unwrap());
        assert_ne!(key(&p), key(&q));
    }
    #[test]
    fn full_position_verification_rejects_a_forced_hash_collision() {
        let p = position();
        let mut q = p;
        q.turn = Side::Black;
        let mut table = Table::new(1);
        let pv = vec![p.choose_move().unwrap()];
        table.store_key(7, p, 4, true, 0, 12, Bound::Exact, &pv);
        assert!(!table.lookup_key(7, q, 4, true, 0, -100, 100).hit);
        assert_eq!(
            table
                .lookup_key(7, p, 4, true, 0, -100, 100)
                .cutoff
                .unwrap()
                .0,
            12
        );
    }
    #[test]
    fn bounds_depth_and_history_are_required_for_score_reuse() {
        let p = position();
        let pv = vec![p.choose_move().unwrap()];
        for (bound, alpha, beta, cutoff) in [
            (Bound::Exact, -100, 100, true),
            (Bound::Lower, 0, 10, true),
            (Bound::Lower, 0, 20, false),
            (Bound::Upper, 15, 20, true),
            (Bound::Upper, 0, 20, false),
        ] {
            let mut t = Table::new(1);
            t.store(p, 4, true, 0, 12, bound, &pv);
            assert_eq!(
                t.lookup(p, 4, true, 0, alpha, beta).cutoff.is_some(),
                cutoff
            );
            assert!(t.lookup(p, 3, true, 0, alpha, beta).cutoff.is_none());
            let dirty = t.lookup(p, 4, false, 0, alpha, beta);
            assert!(dirty.hit);
            assert_eq!(dirty.best_move, pv.first().cloned());
            assert!(dirty.cutoff.is_none());
        }
        let mut t = Table::new(1);
        t.store(p, 4, false, 0, 12, Bound::Exact, &pv);
        assert!(t.lookup(p, 4, true, 0, -100, 100).cutoff.is_none());
    }
    #[test]
    fn terminal_distance_normalization_and_budget() {
        for score in [-29990, -10, 0, 10, 29990] {
            assert_eq!(from_table(to_table(score, 7), 7), score);
        }
        assert_eq!(from_table(to_table(29990, 7), 3), 29994);
        assert_eq!(from_table(to_table(-29990, 7), 3), -29994);
        for mb in [1, 16, 256] {
            let t = Table::new(mb);
            assert!(
                t.slots.capacity() * (size_of::<Option<Entry>>() + MAX_PV * size_of::<Move>())
                    <= mb * 1024 * 1024
            );
        }
    }
    #[test]
    fn reversible_king_histories_are_not_clean() {
        let p = position();
        let king = p.successor(&p.parse_move("28-22").unwrap());
        let man = p.successor(&p.parse_move("46-41").unwrap());
        assert!(clean_history(&[p]));
        assert!(!clean_history(&[p, king]));
        assert!(clean_history(&[p, man]));
    }
    #[test]
    fn cluster_replacement_is_bounded_and_prefers_old_shallow_entries() {
        let p = position();
        let mv = p.choose_move().unwrap();
        let pv = vec![mv.clone()];
        let mut table = Table::new(1);
        table.start_iteration(1);
        let stride = table.mask as u64 + 1;
        for n in 0..4 {
            table.store_key(
                7 + n * stride,
                p,
                (n + 1) as u8,
                true,
                0,
                n as i32,
                Bound::Exact,
                &pv,
            );
        }
        let capacity = table.slots.len();
        table.start_iteration(2);
        table.store_key(7 + 4 * stride, p, 1, true, 0, 99, Bound::Exact, &pv);
        assert!(!table.lookup_key(7, p, 1, true, 0, -100, 100).hit);
        assert!(
            table
                .lookup_key(7 + 3 * stride, p, 4, true, 0, -100, 100)
                .hit
        );
        assert_eq!(
            table
                .lookup_key(7 + 4 * stride, p, 1, true, 0, -100, 100)
                .cutoff
                .unwrap()
                .0,
            99
        );
        for n in 5..1000 {
            table.store_key(7 + n * stride, p, 1, true, 0, 0, Bound::Exact, &pv);
        }
        assert_eq!(table.slots.len(), capacity);
        let mut fresh = Table::new(1);
        fresh.store(p, 1, true, 0, 0, Bound::Exact, &vec![mv; MAX_PV + 1]);
        assert!(!fresh.lookup(p, 1, true, 0, -100, 100).hit);
    }
    #[test]
    fn king_capture_alone_resets_repetition_context() {
        let p = Position::new(
            Side::White,
            &[
                (Square::new(28).unwrap(), Side::White, Piece::King),
                (Square::new(23).unwrap(), Side::Black, Piece::King),
            ],
            [None; 2],
        )
        .unwrap();
        let child = p.successor(&p.choose_move().unwrap());
        assert_eq!(p.men, child.men);
        assert!(clean_history(&[p, child]));
    }
}
