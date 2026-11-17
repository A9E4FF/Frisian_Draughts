//! Standard draughts FEN describes board placement and turn, not game history.
use crate::{Error, Piece, Position, Side, Square};

impl Position {
    /// Import draughts FEN, e.g. `W:W31-50:B1-20` or `B:WK12,31:BK5,20`.
    /// King restrictions are cleared; use `Position::new` for a full-state fixture.
    pub fn from_fen(fen: &str) -> Result<Self, Error> {
        let fen = fen.trim();
        let fen = fen.strip_suffix('.').unwrap_or(fen);
        let fields: Vec<_> = fen.split(':').map(str::trim).collect();
        if fields.len() != 3 {
            return Err(Error(
                "FEN requires turn and two piece sections: W:W31-50:B1-20".into(),
            ));
        }
        let turn = match fields[0] {
            "W" => Side::White,
            "B" => Side::Black,
            _ => return Err(Error("FEN turn must be W or B".into())),
        };
        let mut seen = [false; 2];
        let mut pieces = Vec::new();
        for field in &fields[1..] {
            let (side, body) = if let Some(body) = field.strip_prefix('W') {
                (Side::White, body)
            } else if let Some(body) = field.strip_prefix('B') {
                (Side::Black, body)
            } else {
                return Err(Error("FEN piece section must start with W or B".into()));
            };
            let i = side.index();
            if seen[i] {
                return Err(Error("duplicate FEN side section".into()));
            }
            seen[i] = true;
            if body.trim().is_empty() {
                continue;
            }
            for token in body.split(',').map(str::trim) {
                let (pc, numbers) = if let Some(n) = token.strip_prefix('K') {
                    (Piece::King, n)
                } else {
                    (Piece::Man, token)
                };
                let range: Vec<_> = numbers.split('-').collect();
                if range.len() > 2 {
                    return Err(Error("invalid FEN square range".into()));
                }
                let number = |s: &str| -> Result<u8, Error> {
                    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
                        return Err(Error("invalid FEN square".into()));
                    }
                    let n = s
                        .parse::<u8>()
                        .map_err(|_| Error("FEN square must be 1–50".into()))?;
                    Square::new(n)?;
                    Ok(n)
                };
                let start = number(range[0])?;
                let end = if range.len() == 2 {
                    number(range[1])?
                } else {
                    start
                };
                if end < start {
                    return Err(Error("FEN ranges must be ascending".into()));
                }
                for n in start..=end {
                    pieces.push((Square::new(n)?, side, pc));
                }
            }
        }
        Self::new(turn, &pieces, [None; 2])
    }
    /// Export only standard FEN fields. Supplement restriction/history state separately.
    pub fn to_fen(&self) -> String {
        let mut result = if self.turn == Side::White {
            "W".to_owned()
        } else {
            "B".to_owned()
        };
        for side in [Side::White, Side::Black] {
            result.push(':');
            result.push(if side == Side::White { 'W' } else { 'B' });
            let tokens: Vec<_> = (1..=50)
                .filter_map(|n| {
                    let sq = Square::new(n).unwrap();
                    self.piece_at(sq).and_then(|(s, p)| {
                        if s == side {
                            Some(format!("{}{n}", if p == Piece::King { "K" } else { "" }))
                        } else {
                            None
                        }
                    })
                })
                .collect();
            result.push_str(&tokens.join(","));
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn starting_ranges_kings_empty_sides_and_roundtrip() {
        assert_eq!(
            Position::from_fen("W:W31-50:B1-20").unwrap(),
            Position::starting()
        );
        for fen in [
            "B:WK12,31:BK5,20",
            "W:W:B1",
            "W:WK1-3:BK48-50.",
            " B : B20,K5 : W31,K12 ",
        ] {
            let p = Position::from_fen(fen).unwrap();
            assert_eq!(Position::from_fen(&p.to_fen()).unwrap(), p);
            assert_eq!(p.restriction(Side::White), None);
        }
    }
    #[test]
    fn malformed_overlapping_or_unpromoted_positions_fail() {
        for fen in [
            "",
            "W:W31",
            "X:W31:B1",
            "W:W31:W32",
            "W:W0:B1",
            "W:WK51:B1",
            "W:W31-30:B1",
            "W:W31,,32:B1",
            "W:W31,31:B1",
            "W:W31:B31",
            "W:W1:B20",
            "W:WK:B1",
            "W:W3 1:B1",
        ] {
            assert!(Position::from_fen(fen).is_err(), "{fen}");
        }
    }
}
