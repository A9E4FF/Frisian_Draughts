//! Frisian draughts rules, a deterministic baseline, and fixed-depth search.
//! Rule behavior adapted from Scan 3.1, Copyright (C) 2015–2019 Fabien Letouzey.
//! SPDX-License-Identifier: GPL-3.0-only
//!
//! ```
//! use frisian_draughts::{Game, Outcome};
//! let mut game = Game::default();
//! let mv = game.position().parse_move("31-26")?;
//! game.play(&mv)?;
//! let reply = game.choose_move().expect("Black has legal moves");
//! game.play(&reply)?;
//! assert_eq!(game.outcome(), Outcome::Ongoing);
//! # Ok::<(), frisian_draughts::Error>(())
//! ```
pub mod search;

use std::fmt;

use bitboard::{squares, SPARSE};
mod bitboard;
mod tt;
#[cfg(test)]
mod reference;

/// Standard square numbering, 1 through 50.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Square(u8);
impl Square {
    pub fn new(n: u8) -> Result<Self, Error> {
        if (1..=50).contains(&n) {
            Ok(Self(n))
        } else {
            Err(Error("square must be 1–50".into()))
        }
    }
    pub fn number(self) -> u8 {
        self.0
    }
    fn bit(self) -> u64 {
        1 << self.index()
    }
    fn index(self) -> usize {
        SPARSE[(self.0 - 1) as usize] as usize
    }
    fn coords(self) -> (i8, i8) {
        let row = (self.0 - 1) / 5;
        (row as i8, (((self.0 - 1) % 5) * 2 + (1 - row % 2)) as i8)
    }
    fn at(row: i8, col: i8) -> Option<Self> {
        if (0..10).contains(&row) && (0..10).contains(&col) && (row + col) % 2 == 1 {
            Some(Self((row * 5 + col / 2 + 1) as u8))
        } else {
            None
        }
    }
    fn step(self, d: (i8, i8)) -> Option<Self> {
        let (r, c) = self.coords();
        Self::at(r + d.0, c + d.1)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Side {
    White,
    Black,
}
impl Side {
    pub fn other(self) -> Self {
        match self {
            Self::White => Self::Black,
            Self::Black => Self::White,
        }
    }
    fn index(self) -> usize {
        if self == Self::White {
            0
        } else {
            1
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Piece {
    Man,
    King,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}

/// Full move identity. Captured squares are a set, not a traversal path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Move {
    from: Square,
    to: Square,
    captured: u64,
}
impl Move {
    pub fn from(&self) -> Square {
        self.from
    }
    pub fn to(&self) -> Square {
        self.to
    }
    pub fn captured(&self) -> Vec<Square> {
        squares(self.captured).collect()
    }
    pub fn is_capture(&self) -> bool {
        self.captured != 0
    }
}
impl fmt::Display for Move {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}{}{}",
            self.from.0,
            if self.is_capture() { "x" } else { "-" },
            self.to.0
        )?;
        for s in self.captured() {
            write!(f, "x{}", s.0)?;
        }
        Ok(())
    }
}
/// The king tracked by the Frisian three-quiet-move restriction.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct KingRestriction {
    square: Square,
    count: u8,
}
impl KingRestriction {
    pub fn new(square: Square, count: u8) -> Result<Self, Error> {
        if (1..=3).contains(&count) {
            Ok(Self { square, count })
        } else {
            Err(Error("king count must be 1–3".into()))
        }
    }
    pub fn square(self) -> Square {
        self.square
    }
    pub fn count(self) -> u8 {
        self.count
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Position {
    men: [u64; 2],
    kings: [u64; 2],
    turn: Side,
    restrictions: [Option<KingRestriction>; 2],
}
impl Default for Position {
    fn default() -> Self {
        Self::starting()
    }
}
impl Position {
    pub fn starting() -> Self {
        let pieces: Vec<_> = (1..=50)
            .filter_map(|n| {
                if n <= 20 {
                    Some((Square(n), Side::Black, Piece::Man))
                } else if n >= 31 {
                    Some((Square(n), Side::White, Piece::Man))
                } else {
                    None
                }
            })
            .collect();
        Self::new(Side::White, &pieces, [None; 2]).expect("valid starting position")
    }
    /// Construct a complete state; restriction entries are ordered White, Black.
    pub fn new(
        turn: Side,
        pieces: &[(Square, Side, Piece)],
        restrictions: [Option<KingRestriction>; 2],
    ) -> Result<Self, Error> {
        let mut p = Self {
            men: [0; 2],
            kings: [0; 2],
            turn,
            restrictions,
        };
        for &(sq, side, pc) in pieces {
            if p.occupied() & sq.bit() != 0 {
                return Err(Error("overlapping pieces".into()));
            }
            if pc == Piece::Man && promotion(sq, side) {
                return Err(Error("unpromoted man on promotion row".into()));
            }
            match pc {
                Piece::Man => p.men[side.index()] |= sq.bit(),
                Piece::King => p.kings[side.index()] |= sq.bit(),
            }
        }
        for (i, r) in restrictions.iter().enumerate() {
            if let Some(r) = r {
                if p.men[i] == 0 || p.kings[i] & r.square.bit() == 0 {
                    return Err(Error(
                        "restriction requires a king and a remaining man".into(),
                    ));
                }
            }
        }
        Ok(p)
    }
    pub fn turn(&self) -> Side {
        self.turn
    }
    pub fn restriction(&self, side: Side) -> Option<KingRestriction> {
        self.restrictions[side.index()]
    }
    pub fn piece_at(&self, sq: Square) -> Option<(Side, Piece)> {
        for side in [Side::White, Side::Black] {
            if self.men[side.index()] & sq.bit() != 0 {
                return Some((side, Piece::Man));
            }
            if self.kings[side.index()] & sq.bit() != 0 {
                return Some((side, Piece::King));
            }
        }
        None
    }
    fn occupied(&self) -> u64 {
        self.men[0] | self.men[1] | self.kings[0] | self.kings[1]
    }
    pub fn legal_moves(&self) -> Vec<Move> {
        #[cfg(test)]
        if reference::enabled() {
            return self.legal_moves_reference();
        }
        let g = bitboard::geometry();
        let i = self.turn.index();
        let j = self.turn.other().index();
        let empty = bitboard::PLAYABLE & !self.occupied();
        let enemy = self.men[j] | self.kings[j];
        let mut captures = Vec::new();
        // Find all men with an adjacent victim and an empty landing in parallel.
        for (d, &reverse) in bitboard::OPPOSITE.iter().enumerate() {
            let froms = self.men[i]
                & bitboard::shift(enemy, reverse)
                & bitboard::shift(bitboard::shift(empty, reverse), reverse);
            for from in squares(froms) {
                let (jump, to) = g.man_jumps[from.index()][d].expect("validated capture geometry");
                self.capture_bits(
                    from,
                    Square(bitboard::STANDARD[to as usize]),
                    false,
                    1u64 << jump,
                    &mut captures,
                );
            }
        }
        for from in squares(self.kings[i]) {
            self.capture_bits(from, from, true, 0, &mut captures);
        }
        let mut moves = if captures.is_empty() {
            let mut quiet = Vec::new();
            let directions = if self.turn == Side::White { 0..2 } else { 2..4 };
            for d in directions {
                let froms = self.men[i] & bitboard::shift(empty, bitboard::OPPOSITE[d]);
                for from in squares(froms) {
                    let to = Square(bitboard::STANDARD[g.next[from.index()][d] as usize]);
                    quiet.push(Move {
                        from,
                        to,
                        captured: 0,
                    });
                }
            }
            for from in squares(self.kings[i]) {
                if self.restrictions[i].is_some_and(|r| r.square == from && r.count == 3) {
                    continue;
                }
                let targets =
                    g.attack(from.index(), g.king_moves[from.index()], self.occupied()) & empty;
                for to in squares(targets) {
                    quiet.push(Move {
                        from,
                        to,
                        captured: 0,
                    });
                }
            }
            quiet
        } else {
            let score = |m: &Move| {
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
    fn capture_bits(
        &self,
        start: Square,
        from: Square,
        king: bool,
        captured: u64,
        out: &mut Vec<Move>,
    ) {
        let g = bitboard::geometry();
        // Captured victims are excluded from future captures but remain blockers.
        let blockers = self.occupied() & !start.bit();
        let empty = bitboard::PLAYABLE & !blockers;
        let j = self.turn.other().index();
        let enemy = (self.men[j] | self.kings[j]) & !captured;
        let mut extended = false;
        if king {
            for jump in squares(g.king_targets[from.index()] & enemy) {
                if g.capture_path[from.index()][jump.index()] & !empty != 0 {
                    continue;
                }
                let d = g.direction[from.index()][jump.index()];
                let targets = g.attack(jump.index(), g.rays[jump.index()][d], blockers) & empty;
                for to in squares(targets) {
                    extended = true;
                    self.capture_bits(start, to, true, captured | jump.bit(), out);
                }
            }
        } else {
            for &(jump, to) in g.man_jumps[from.index()].iter().flatten() {
                if enemy & (1u64 << jump) != 0 && empty & (1u64 << to) != 0 {
                    extended = true;
                    self.capture_bits(
                        start,
                        Square(bitboard::STANDARD[to as usize]),
                        false,
                        captured | (1u64 << jump),
                        out,
                    );
                }
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
    /// Stable first legal move. No search, sleep, or artificial delay.
    pub fn choose_move(&self) -> Option<Move> {
        self.legal_moves().into_iter().next()
    }
    pub fn apply(&mut self, mv: &Move) -> Result<(), Error> {
        if !self.legal_moves().contains(mv) {
            return Err(Error("illegal move".into()));
        }
        *self = self.successor(mv);
        Ok(())
    }
    fn successor(&self, mv: &Move) -> Self {
        let mut p = *self;
        let i = self.turn.index();
        let j = self.turn.other().index();
        let king = self.kings[i] & mv.from.bit() != 0;
        p.men[i] &= !mv.from.bit();
        p.kings[i] &= !mv.from.bit();
        if king || promotion(mv.to, self.turn) {
            p.kings[i] |= mv.to.bit();
        } else {
            p.men[i] |= mv.to.bit();
        }
        p.men[j] &= !mv.captured;
        p.kings[j] &= !mv.captured;
        p.restrictions = [None; 2];
        if let Some(r) = self.restrictions[j] {
            if p.men[j] != 0 && p.kings[j] & r.square.bit() != 0 {
                p.restrictions[j] = Some(r);
            }
        }
        if king && mv.captured == 0 && p.men[i] != 0 {
            let count = self.restrictions[i]
                .filter(|r| r.square == mv.from)
                .map_or(1, |r| r.count + 1);
            p.restrictions[i] = Some(KingRestriction {
                square: mv.to,
                count,
            });
        }
        p.turn = self.turn.other();
        p
    }
    /// Resolve endpoint notation or exact captured-set notation; reject ambiguity.
    pub fn parse_move(&self, text: &str) -> Result<Move, Error> {
        let text = text.trim();
        let cap = text.contains('x');
        let parts: Vec<_> = text.split(if cap { 'x' } else { '-' }).collect();
        if parts.len() < 2 || (!cap && parts.len() != 2) {
            return Err(Error("use 32-28 or 32x23[xcaptured...]".into()));
        }
        let nums: Result<Vec<_>, _> = parts
            .iter()
            .map(|s| {
                s.parse::<u8>()
                    .map_err(|_| Error("invalid square".into()))
                    .and_then(Square::new)
            })
            .collect();
        let nums = nums?;
        let mut caps: Vec<_> = nums[2..].to_vec();
        caps.sort();
        if caps.windows(2).any(|w| w[0] == w[1]) {
            return Err(Error("duplicate captured square".into()));
        }
        let matches: Vec<_> = self
            .legal_moves()
            .into_iter()
            .filter(|m| {
                m.from == nums[0]
                    && m.to == nums[1]
                    && m.is_capture() == cap
                    && (caps.is_empty() || m.captured() == caps)
            })
            .collect();
        match matches.len() {
            1 => Ok(matches[0].clone()),
            0 => Err(Error(
                "illegal move; use moves to list legal choices".into(),
            )),
            _ => Err(Error(format!(
                "ambiguous move; choose {}",
                matches
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            ))),
        }
    }
}
fn promotion(sq: Square, side: Side) -> bool {
    sq.bit() & bitboard::PROMOTION[side.index()] != 0
}
impl fmt::Display for Position {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for r in 0..10 {
            for c in 0..10 {
                match Square::at(r, c) {
                    None => write!(f, "    ")?,
                    Some(s) => match self.piece_at(s) {
                        Some((side, pc)) => write!(
                            f,
                            " {:>2} ",
                            match (side, pc) {
                                (Side::White, Piece::Man) => "w",
                                (Side::White, Piece::King) => "W",
                                (Side::Black, Piece::Man) => "b",
                                (Side::Black, Piece::King) => "B",
                            }
                        )?,
                        None => write!(f, " {:>2} ", s.0)?,
                    },
                }
            }
            writeln!(f)?;
        }
        write!(f, "{:?} to move", self.turn)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Outcome {
    Ongoing,
    Won(Side),
    Draw,
}
#[derive(Clone, Debug)]
pub struct Game {
    history: Vec<Position>,
}
impl Default for Game {
    fn default() -> Self {
        Self::new(Position::starting())
    }
}
impl Game {
    pub fn new(position: Position) -> Self {
        Self {
            history: vec![position],
        }
    }
    pub fn position(&self) -> &Position {
        self.history.last().unwrap()
    }
    pub fn ply(&self) -> usize {
        self.history.len() - 1
    }
    pub fn outcome(&self) -> Outcome {
        let p = self.position();
        if p.legal_moves().is_empty() {
            Outcome::Won(p.turn.other())
        } else if self.history.iter().filter(|q| *q == p).count() >= 3 {
            Outcome::Draw
        } else {
            Outcome::Ongoing
        }
    }
    pub fn play(&mut self, mv: &Move) -> Result<(), Error> {
        if self.outcome() != Outcome::Ongoing {
            return Err(Error("game has ended".into()));
        }
        let mut next = *self.position();
        next.apply(mv)?;
        self.history.push(next);
        Ok(())
    }
    pub fn choose_move(&self) -> Option<Move> {
        if self.outcome() == Outcome::Ongoing {
            self.position().choose_move()
        } else {
            None
        }
    }
    /// Restore an earlier ply, including all repetition and restriction state.
    pub fn undo_to(&mut self, ply: usize) -> Result<(), Error> {
        if ply >= self.history.len() {
            return Err(Error("cannot undo to a future ply".into()));
        }
        self.history.truncate(ply + 1);
        Ok(())
    }
}
