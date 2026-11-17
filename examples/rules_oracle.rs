//! Line-oriented adapter used only by tools/differential.py.
use frisian_draughts::{Piece, Position, Side, Square};
use std::io::{self, BufRead, Write};
fn main() {
    let mut p = Position::starting();
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let (cmd, arg) = line.split_once(' ').unwrap();
        match cmd {
            "new" => {
                assert_eq!(arg.len(), 51);
                let mut chars = arg.chars();
                let turn = if chars.next().unwrap() == 'W' {
                    Side::White
                } else {
                    Side::Black
                };
                let pieces: Vec<_> = chars
                    .enumerate()
                    .filter_map(|(i, c)| {
                        let (side, pc) = match c {
                            'w' => (Side::White, Piece::Man),
                            'W' => (Side::White, Piece::King),
                            'b' => (Side::Black, Piece::Man),
                            'B' => (Side::Black, Piece::King),
                            'e' => return None,
                            _ => panic!("invalid piece"),
                        };
                        Some((Square::new(i as u8 + 1).unwrap(), side, pc))
                    })
                    .collect();
                p = Position::new(turn, &pieces, [None; 2]).unwrap();
            }
            "play" => {
                let mv = p.parse_move(arg).unwrap();
                p.apply(&mv).unwrap();
            }
            _ => panic!("invalid command"),
        }
        let mut state = String::from(if p.turn() == Side::White { "W" } else { "B" });
        for n in 1..=50 {
            state.push(match p.piece_at(Square::new(n).unwrap()) {
                None => 'e',
                Some((Side::White, Piece::Man)) => 'w',
                Some((Side::White, Piece::King)) => 'W',
                Some((Side::Black, Piece::Man)) => 'b',
                Some((Side::Black, Piece::King)) => 'B',
            });
        }
        for side in [Side::White, Side::Black] {
            let (count, sq) = p
                .restriction(side)
                .map_or((0, 0), |r| (r.count(), r.square().number()));
            state.push_str(&format!(",{count}:{sq}"));
        }
        let mut moves: Vec<_> = p.legal_moves().iter().map(ToString::to_string).collect();
        moves.sort();
        println!("{state}|{}", moves.join(" "));
        io::stdout().flush().unwrap();
    }
}
