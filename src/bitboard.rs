//! Scan-compatible padded geometry and bit operations (GPL-3.0-only).
//! Adapted from Scan 3.1, Copyright (C) 2015–2019 Fabien Letouzey.
//! Geometry is derived once; runtime generation does not traverse coordinates.
use crate::Square;
use std::sync::OnceLock;

pub(super) const SPARSE: [u8; 50] = [
    0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30, 32,
    33, 34, 35, 36, 39, 40, 41, 42, 43, 45, 46, 47, 48, 49, 52, 53, 54, 55, 56, 58, 59, 60, 61, 62,
];
const fn inverse() -> [u8; 64] {
    let mut result = [0; 64];
    let mut i = 0;
    while i < 50 {
        result[SPARSE[i] as usize] = i as u8 + 1;
        i += 1;
    }
    result
}
pub(super) const STANDARD: [u8; 64] = inverse();
pub(super) const PLAYABLE: u64 = 0x7DF3EF9F7CFBE7DF;
pub(super) const DELTAS: [(i8, i8); 8] = [
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
    (-2, 0),
    (2, 0),
    (0, -2),
    (0, 2),
];
const OFFSETS: [i8; 8] = [-7, -6, 6, 7, -13, 13, -1, 1];
pub(super) const OPPOSITE: [usize; 8] = [3, 2, 1, 0, 5, 4, 7, 6];
pub(super) const NONE: u8 = 63;
const fn regions(files: bool) -> [u64; 10] {
    let mut result = [0; 10];
    let mut n = 0;
    while n < 50 {
        let row = n / 5;
        let col = (n % 5) * 2 + 1 - row % 2;
        let index = if files { col } else { row };
        result[index] |= 1u64 << SPARSE[n];
        n += 1;
    }
    result
}
pub(super) const FILES: [u64; 10] = regions(true);
pub(super) const RANKS: [u64; 10] = regions(false);
pub(super) const PROMOTION: [u64; 2] = [RANKS[0], RANKS[9]];
pub(super) const OUTER_FILES: u64 = FILES[0] | FILES[9];
pub(super) const ADJACENT_FILES: u64 = FILES[1] | FILES[8];
const fn valid_sources() -> [u64; 8] {
    let mut result = [0; 8];
    let mut d = 0;
    while d < 8 {
        let mut n = 0;
        while n < 50 {
            let row = (n / 5) as i8;
            let col = ((n % 5) * 2 + 1 - (n / 5) % 2) as i8;
            let r = row + DELTAS[d].0;
            let c = col + DELTAS[d].1;
            if r >= 0 && r < 10 && c >= 0 && c < 10 {
                result[d] |= 1u64 << SPARSE[n];
            }
            n += 1;
        }
        d += 1;
    }
    result
}
const SOURCES: [u64; 8] = valid_sources();
/// Shift one playable step, excluding sources that would cross a boundary.
pub(super) fn shift(bits: u64, direction: usize) -> u64 {
    let bits = bits & SOURCES[direction];
    let offset = OFFSETS[direction];
    let shifted = if offset < 0 {
        bits >> (-offset as u32)
    } else {
        bits << offset as u32
    };
    shifted & PLAYABLE
}
/// Ascending standard-square order; visits only set playable bits.
pub(super) fn squares(bits: u64) -> impl Iterator<Item = Square> {
    let mut bits = bits & PLAYABLE;
    std::iter::from_fn(move || {
        if bits == 0 {
            return None;
        }
        let index = bits.trailing_zeros() as usize;
        bits &= bits - 1;
        Some(Square(STANDARD[index]))
    })
}

pub(super) struct Geometry {
    pub next: [[u8; 8]; 63],
    pub rays: [[u64; 8]; 63],
    pub beyond: [[u64; 63]; 63],
    pub capture_path: [[u64; 63]; 63],
    pub direction: [[usize; 63]; 63],
    pub king_moves: [u64; 63],
    pub king_targets: [u64; 63],
    pub man_jumps: [[Option<(u8, u8)>; 8]; 63],
}
impl Geometry {
    fn build() -> Self {
        let mut g = Self {
            next: [[NONE; 8]; 63],
            rays: [[0; 8]; 63],
            beyond: [[0; 63]; 63],
            capture_path: [[0; 63]; 63],
            direction: [[0; 63]; 63],
            king_moves: [0; 63],
            king_targets: [0; 63],
            man_jumps: [[None; 8]; 63],
        };
        for from in squares(PLAYABLE) {
            let i = from.index();
            for (d, delta) in DELTAS.iter().enumerate() {
                if let Some(to) = from.step(*delta) {
                    g.next[i][d] = to.index() as u8;
                }
                let mut next = from.step(*delta);
                while let Some(to) = next {
                    g.rays[i][d] |= to.bit();
                    next = to.step(*delta);
                }
                if d < 4 {
                    g.king_moves[i] |= g.rays[i][d];
                }
            }
        }
        for from in squares(PLAYABLE) {
            let i = from.index();
            for d in 0..8 {
                let jump = g.next[i][d];
                if jump != NONE {
                    let to = g.next[jump as usize][d];
                    if to != NONE {
                        g.man_jumps[i][d] = Some((jump, to));
                    }
                }
                let mut path = 0;
                let mut next = g.next[i][d];
                while next != NONE {
                    let j = next as usize;
                    g.direction[i][j] = d;
                    g.beyond[i][j] = g.rays[j][d];
                    let behind = g.next[j][d];
                    if behind != NONE {
                        g.king_targets[i] |= 1u64 << j;
                        g.capture_path[i][j] = path | (1u64 << behind);
                    }
                    path |= 1u64 << j;
                    next = behind;
                }
            }
        }
        g
    }
    /// Trim everything beyond blockers, retaining the first blocker itself.
    pub fn attack(&self, from: usize, mut targets: u64, occupied: u64) -> u64 {
        for blocker in squares(targets & occupied) {
            targets &= !self.beyond[from][blocker.index()];
        }
        targets
    }
}
pub(super) fn geometry() -> &'static Geometry {
    static GEOMETRY: OnceLock<Geometry> = OnceLock::new();
    GEOMETRY.get_or_init(Geometry::build)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn iteration_masks_and_square_conversions() {
        assert_eq!(squares(0).count(), 0);
        assert_eq!(
            squares(u64::MAX).map(|s| s.number()).collect::<Vec<_>>(),
            (1..=50).collect::<Vec<_>>()
        );
        assert_eq!(FILES.iter().copied().fold(0, |a, b| a | b), PLAYABLE);
        assert_eq!(RANKS.iter().copied().fold(0, |a, b| a | b), PLAYABLE);
        assert_eq!(OUTER_FILES & ADJACENT_FILES, 0);
        for n in 1..=50 {
            let sq = Square::new(n).unwrap();
            let (row, col) = sq.coords();
            assert_eq!(STANDARD[sq.index()], n);
            assert_eq!(FILES[col as usize] & sq.bit(), sq.bit());
            assert_eq!(RANKS[row as usize] & sq.bit(), sq.bit());
            assert_eq!(PROMOTION[0] & sq.bit() != 0, row == 0);
            assert_eq!(PROMOTION[1] & sq.bit() != 0, row == 9);
        }
    }
    #[test]
    fn all_directions_rays_and_capture_paths_match_coordinates() {
        let g = geometry();
        for n in 1..=50 {
            let from = Square::new(n).unwrap();
            let i = from.index();
            let mut move_mask = 0;
            let mut capture_mask = 0;
            for (d, delta) in DELTAS.iter().enumerate() {
                let next = from.step(*delta);
                assert_eq!(
                    shift(from.bit(), d),
                    next.map_or(0, |sq| sq.bit()),
                    "square {n}, dir {d}"
                );
                assert_eq!(g.next[i][d], next.map_or(NONE, |sq| sq.index() as u8));
                let jump = next.and_then(|sq| {
                    sq.step(*delta)
                        .map(|to| (sq.index() as u8, to.index() as u8))
                });
                assert_eq!(g.man_jumps[i][d], jump);
                let mut ray = 0;
                let mut path = 0;
                let mut current = next;
                while let Some(victim) = current {
                    ray |= victim.bit();
                    assert_eq!(g.direction[i][victim.index()], d);
                    let mut beyond = 0;
                    let mut to = victim.step(*delta);
                    while let Some(sq) = to {
                        beyond |= sq.bit();
                        to = sq.step(*delta);
                    }
                    assert_eq!(g.beyond[i][victim.index()], beyond);
                    if let Some(behind) = victim.step(*delta) {
                        capture_mask |= victim.bit();
                        assert_eq!(g.capture_path[i][victim.index()], path | behind.bit());
                    }
                    path |= victim.bit();
                    current = victim.step(*delta);
                }
                assert_eq!(g.rays[i][d], ray);
                if d < 4 {
                    move_mask |= ray;
                }
            }
            assert_eq!(g.king_moves[i], move_mask);
            assert_eq!(g.king_targets[i], capture_mask);
        }
    }
    #[test]
    fn blocker_trimming_matches_coordinate_walks() {
        let mut seed = 137u64;
        let g = geometry();
        for _ in 0..100 {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            let occupied = seed & PLAYABLE;
            for from in squares(PLAYABLE) {
                for (d, delta) in DELTAS.iter().enumerate() {
                    let mut expected = 0;
                    let mut next = from.step(*delta);
                    while let Some(sq) = next {
                        expected |= sq.bit();
                        if occupied & sq.bit() != 0 {
                            break;
                        }
                        next = sq.step(*delta);
                    }
                    assert_eq!(
                        g.attack(from.index(), g.rays[from.index()][d], occupied),
                        expected
                    );
                }
            }
        }
    }
}
