use frisian_draughts::{Game, KingRestriction, Outcome, Piece, Position, Side, Square};
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

fn sq(n: u8) -> Square {
    Square::new(n).unwrap()
}
fn position(
    turn: Side,
    pieces: &[(u8, Side, Piece)],
    restrictions: [Option<KingRestriction>; 2],
) -> Position {
    Position::new(
        turn,
        &pieces
            .iter()
            .map(|&(n, s, p)| (sq(n), s, p))
            .collect::<Vec<_>>(),
        restrictions,
    )
    .unwrap()
}
fn play(p: &mut Position, text: &str) {
    let mv = p.parse_move(text).unwrap();
    p.apply(&mv).unwrap();
}
use Piece::{King, Man};
use Side::{Black, White};

#[test]
fn starting_moves_and_deterministic_choice() {
    let p = Position::starting();
    assert_eq!(p.legal_moves().len(), 9);
    assert_eq!(p.choose_move().unwrap().to_string(), "31-26");
    assert!(p.legal_moves().iter().all(|m| !m.is_capture()));
}
#[test]
fn captures_in_diagonal_orthogonal_and_backward_directions() {
    for (enemy, to) in [(23, 19), (27, 26), (33, 39), (18, 8)] {
        let p = position(White, &[(28, White, Man), (enemy, Black, Man)], [None; 2]);
        let mv = p.parse_move(&format!("28x{to}")).unwrap();
        assert_eq!(mv.captured(), vec![sq(enemy)]);
        assert!(p.legal_moves().iter().all(|m| m.is_capture()));
    }
}
#[test]
fn weighted_priority_and_capturing_king_tie_break() {
    let p = position(
        White,
        &[(28, White, Man), (27, Black, Man), (23, Black, King)],
        [None; 2],
    );
    assert!(p.legal_moves().iter().all(|m| m.captured() == vec![sq(23)]));
    let p = position(
        White,
        &[(28, White, Man), (38, White, King), (33, Black, Man)],
        [None; 2],
    );
    assert!(p.legal_moves().iter().all(|m| m.from() == sq(38)));
}
#[test]
fn multi_capture_must_finish_and_captured_pieces_block() {
    let p = position(
        White,
        &[(28, White, Man), (23, Black, Man), (14, Black, Man)],
        [None; 2],
    );
    assert!(p.legal_moves().iter().all(|m| m.captured().len() == 2));
    assert!(p.parse_move("28x19").is_err());
    let p = position(
        White,
        &[(28, White, King), (23, Black, Man), (32, Black, Man)],
        [None; 2],
    );
    // Opposite diagonal victims cannot both be jumped: the first remains a blocker.
    assert!(p.legal_moves().iter().all(|m| m.captured().len() == 1));
}
#[test]
fn flying_king_has_multiple_landing_choices() {
    let p = position(White, &[(28, White, King), (23, Black, Man)], [None; 2]);
    assert!(p.legal_moves().len() > 1);
    assert!(p.legal_moves().iter().any(|m| m.to() == sq(19)));
    assert!(p.legal_moves().iter().any(|m| m.to() == sq(5)));
}
#[test]
fn promotion_only_at_final_landing() {
    let mut p = position(
        White,
        &[(11, White, Man), (7, Black, Man), (8, Black, Man)],
        [None; 2],
    );
    // 11 -> 2 -> 13 crosses the promotion rank but ends as a man.
    play(&mut p, "11x13");
    assert_eq!(p.piece_at(sq(13)), Some((White, Man)));
    let mut p = position(White, &[(11, White, Man), (7, Black, Man)], [None; 2]);
    play(&mut p, "11x2");
    assert_eq!(p.piece_at(sq(2)), Some((White, King)));
    let mut p = position(White, &[(6, White, Man), (50, Black, King)], [None; 2]);
    play(&mut p, "6-1");
    assert_eq!(p.piece_at(sq(1)), Some((White, King)));
}
#[test]
fn fourth_quiet_king_move_is_forbidden_but_capture_is_allowed() {
    let r = KingRestriction::new(sq(28), 3).unwrap();
    let p = position(
        White,
        &[(28, White, King), (46, White, Man), (5, Black, King)],
        [Some(r), None],
    );
    assert!(p.legal_moves().iter().all(|m| m.from() != sq(28)));
    let mut p = position(
        White,
        &[(28, White, King), (46, White, Man), (23, Black, Man)],
        [Some(r), None],
    );
    let mv = p.choose_move().unwrap();
    assert!(mv.is_capture());
    p.apply(&mv).unwrap();
    assert_eq!(p.restriction(White), None);
}
#[test]
fn restriction_updates_preserves_and_resets() {
    let r = KingRestriction::new(sq(28), 2).unwrap();
    let mut p = position(
        White,
        &[
            (28, White, King),
            (46, White, Man),
            (5, Black, King),
            (1, Black, Man),
        ],
        [Some(r), None],
    );
    play(&mut p, "28-22");
    assert_eq!(p.restriction(White).unwrap().count(), 3);
    play(&mut p, "5-10");
    assert_eq!(p.restriction(White).unwrap().count(), 3);
    play(&mut p, "46-41");
    assert_eq!(p.restriction(White), None);
    let mut p = position(
        White,
        &[
            (28, White, King),
            (30, White, King),
            (46, White, Man),
            (1, Black, Man),
        ],
        [Some(r), None],
    );
    play(&mut p, "30-25");
    assert_eq!(p.restriction(White).unwrap().count(), 1);
}
#[test]
fn capture_removes_opponent_restriction_when_king_or_last_man_disappears() {
    for (victim, tracked) in [(King, 23), (Man, 5)] {
        let r = KingRestriction::new(sq(tracked), 2).unwrap();
        let mut pieces = vec![(28, White, Man), (23, Black, victim)];
        if victim == King {
            pieces.push((1, Black, Man));
        } else {
            pieces.push((5, Black, King));
        }
        let mut p = position(White, &pieces, [None, Some(r)]);
        let mv = p.choose_move().unwrap();
        p.apply(&mv).unwrap();
        assert_eq!(p.restriction(Black), None);
    }
}
#[test]
fn restriction_changes_equality_and_hash() {
    let pieces = [(28, White, King), (46, White, Man), (1, Black, Man)];
    let p = position(White, &pieces, [None; 2]);
    let q = position(
        White,
        &pieces,
        [Some(KingRestriction::new(sq(28), 3).unwrap()), None],
    );
    let hash = |p: Position| {
        let mut h = DefaultHasher::new();
        p.hash(&mut h);
        h.finish()
    };
    assert_ne!(p, q);
    assert_ne!(hash(p), hash(q));
    assert_ne!(p.legal_moves(), q.legal_moves());
}
#[test]
fn invalid_positions_and_input_are_rejected_without_mutation() {
    assert!(Square::new(0).is_err());
    assert!(Square::new(51).is_err());
    assert!(KingRestriction::new(sq(28), 4).is_err());
    assert!(Position::new(White, &[(sq(1), White, Man)], [None; 2]).is_err());
    assert!(Position::new(
        White,
        &[(sq(28), White, King), (sq(28), Black, King)],
        [None; 2]
    )
    .is_err());
    assert!(Position::new(
        White,
        &[],
        [Some(KingRestriction::new(sq(28), 1).unwrap()), None]
    )
    .is_err());
    let mut p = Position::starting();
    let before = p;
    for s in ["", "32-99", "32-27-22", "32x27", "hello", "32x23x24x24"] {
        assert!(p.parse_move(s).is_err());
    }
    let foreign = position(White, &[(28, White, King), (23, Black, Man)], [None; 2])
        .choose_move()
        .unwrap();
    assert!(p.apply(&foreign).is_err());
    assert_eq!(p, before);
}
#[test]
fn terminal_game_does_not_select_a_move() {
    for pieces in [
        vec![(1, Black, Man)],
        vec![(6, White, Man), (1, Black, Man)],
    ] {
        let mut game = Game::new(position(White, &pieces, [None; 2]));
        assert_eq!(game.outcome(), Outcome::Won(Black));
        assert!(game.choose_move().is_none());
        assert!(game.undo_to(1).is_err());
    }
}
#[test]
fn threefold_repetition_and_undo_restore_history() {
    let p = position(White, &[(1, White, King), (5, Black, King)], [None; 2]);
    let mut game = Game::new(p);
    for _ in 0..2 {
        for text in ["1-12", "5-10", "12-1", "10-5"] {
            let mv = game.position().parse_move(text).unwrap();
            game.play(&mv).unwrap();
        }
    }
    assert_eq!(game.outcome(), Outcome::Draw);
    assert!(game.choose_move().is_none());
    game.undo_to(0).unwrap();
    assert_eq!(*game.position(), p);
    assert_eq!(game.outcome(), Outcome::Ongoing);
    let mut g = Game::new(position(
        White,
        &[(28, White, King), (46, White, Man), (1, Black, Man)],
        [None; 2],
    ));
    let before = *g.position();
    let mv = g.position().parse_move("28-22").unwrap();
    g.play(&mv).unwrap();
    g.undo_to(0).unwrap();
    assert_eq!(*g.position(), before);
}
#[test]
fn reproducible_playouts_preserve_material_and_notation() {
    let mut seed = 713u64;
    for _ in 0..30 {
        let mut game = Game::default();
        for _ in 0..160 {
            if game.outcome() != Outcome::Ongoing {
                break;
            }
            let p = *game.position();
            let moves = p.legal_moves();
            assert_eq!(game.choose_move(), moves.first().cloned());
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            let mv = &moves[(seed as usize) % moves.len()];
            assert_eq!(p.parse_move(&mv.to_string()).unwrap(), *mv);
            let count = |p: &Position| (1..=50).filter(|&n| p.piece_at(sq(n)).is_some()).count();
            game.play(mv).unwrap();
            assert_eq!(count(game.position()) + mv.captured().len(), count(&p));
            assert_eq!(game.position().turn(), p.turn().other());
        }
    }
}

#[test]
fn two_captured_men_outrank_one_captured_king() {
    let p = position(
        White,
        &[
            (28, White, Man),
            (27, Black, Man),
            (16, Black, Man),
            (23, Black, King),
        ],
        [None; 2],
    );
    assert!(p
        .legal_moves()
        .iter()
        .all(|m| m.captured() == vec![sq(16), sq(27)]));
    assert!(!p.legal_moves().is_empty());
}
#[test]
fn capture_can_return_to_origin() {
    let mut p = position(
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
        [None; 2],
    );
    let mv = p.parse_move("45x45x8x12x18x33x40x44").unwrap();
    p.apply(&mv).unwrap();
    assert_eq!(p.piece_at(sq(45)), Some((White, King)));
    for n in [8, 12, 18, 33, 40, 44] {
        assert_eq!(p.piece_at(sq(n)), None);
    }
}
#[test]
fn captures_with_same_endpoints_remain_distinct() {
    let p = position(
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
        [None; 2],
    );
    let error = p.parse_move("49x47").unwrap_err().to_string();
    assert!(error.contains("ambiguous"));
    let a = p.parse_move("49x47x7x11x19x30x42").unwrap();
    let b = p.parse_move("49x47x7x11x19x34x42").unwrap();
    assert_ne!(a, b);
    let mut pa = p;
    let mut pb = p;
    pa.apply(&a).unwrap();
    pb.apply(&b).unwrap();
    assert_ne!(pa, pb);
}
