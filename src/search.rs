//! Fixed-depth, single-threaded alpha-beta with mandatory-capture quiescence.
//! Search design follows Scan 3.1 (Fabien Letouzey); GPL-3.0-only.
use crate::{bitboard, tt, Error, Game, Move, Position, Side};
use std::time::{Duration, Instant};

const MATE: i32 = 30_000;
const INF: i32 = 32_000;

/// A complete multi-capture move counts as one ply. Quiescence is additional.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SearchLimits {
    max_depth: u8,
    tt_enabled: bool,
    tt_megabytes: usize,
}
impl Default for SearchLimits {
    fn default() -> Self {
        Self {
            max_depth: 10,
            tt_enabled: true,
            tt_megabytes: 16,
        }
    }
}
impl SearchLimits {
    pub fn new(max_depth: u8) -> Result<Self, Error> {
        if (1..=64).contains(&max_depth) {
            Ok(Self {
                max_depth,
                ..Self::default()
            })
        } else {
            Err(Error("depth must be 1–64".into()))
        }
    }
    pub fn max_depth(self) -> u8 {
        self.max_depth
    }
    pub fn with_tt_enabled(mut self, enabled: bool) -> Self {
        self.tt_enabled = enabled;
        self
    }
    pub fn tt_enabled(self) -> bool {
        self.tt_enabled
    }
    pub fn with_tt_megabytes(mut self, megabytes: usize) -> Result<Self, Error> {
        if !(1..=256).contains(&megabytes) {
            return Err(Error("TT memory must be 1–256 MiB".into()));
        }
        self.tt_megabytes = megabytes;
        Ok(self)
    }
    pub fn tt_megabytes(self) -> usize {
        self.tt_megabytes
    }
}

#[derive(Clone, Debug)]
pub struct SearchResult {
    pub best_move: Option<Move>,
    /// Side-to-move score; absent for an immediate sole-legal-move selection.
    pub score: Option<i32>,
    pub principal_variation: Vec<Move>,
    /// Zero for terminal positions or immediate sole-legal-move selection.
    pub completed_depth: u8,
    /// All visited nodes, including quiescence, across every iteration.
    pub nodes: u64,
    pub quiescence_nodes: u64,
    pub elapsed: Duration,
    pub tt_probes: u64,
    pub tt_hits: u64,
    pub tt_cutoffs: u64,
}

/// Provisional, symmetric material/edge evaluator, from the side to move.
/// Edge bonuses apply only to men; capture-priority weights are not material values.
pub fn evaluate(position: &Position) -> i32 {
    #[cfg(test)]
    if crate::reference::enabled() {
        return crate::reference::evaluate(position);
    }
    let mut white = 0;
    for side in [Side::White, Side::Black] {
        let i = side.index();
        let mut value =
            position.men[i].count_ones() as i32 * 100 + position.kings[i].count_ones() as i32 * 300;
        value += 8 * (position.men[i] & bitboard::OUTER_FILES).count_ones() as i32
            + 4 * (position.men[i] & bitboard::ADJACENT_FILES).count_ones() as i32;
        if let Some(restriction) = position.restrictions[i] {
            value -= [0, 2, 6, 12][restriction.count as usize];
        }
        white += if side == Side::White { value } else { -value };
    }
    if position.turn == Side::White {
        white
    } else {
        -white
    }
}

/// Search without mutating the game. There is deliberately no hidden time limit.
/// Competing captures are searched; a single legal move is returned immediately.
pub fn search(game: &Game, limits: SearchLimits) -> SearchResult {
    search_with_reporter(game, limits, |_| {})
}

/// Reports each completed depth, or once for a terminal/sole-move fast path.
/// The callback runs synchronously and receives cumulative counters.
pub fn search_with_reporter(
    game: &Game,
    limits: SearchLimits,
    mut reporter: impl FnMut(&SearchResult),
) -> SearchResult {
    let start = Instant::now();
    let position = *game.position();
    let moves = position.legal_moves();
    let mut result = SearchResult {
        best_move: None,
        score: None,
        principal_variation: Vec::new(),
        completed_depth: 0,
        nodes: 0,
        quiescence_nodes: 0,
        elapsed: Duration::ZERO,
        tt_probes: 0,
        tt_hits: 0,
        tt_cutoffs: 0,
    };
    if moves.is_empty() {
        result.score = Some(-MATE);
    } else if repeated(&game.history, position) {
        result.score = Some(0);
    } else if moves.len() == 1 {
        result.best_move = Some(moves[0].clone());
        result.principal_variation = moves;
    } else {
        let mut context = Context::new(game.history.clone(), limits);
        let mut previous = Vec::new();
        for depth in 1..=limits.max_depth {
            if let Some(table) = &mut context.table {
                table.start_iteration(depth);
            }
            let (score, pv) = context.negamax(position, depth, 0, -INF, INF, &previous);
            result.best_move = pv.first().cloned();
            result.score = Some(score);
            result.completed_depth = depth;
            previous = pv;
            result.principal_variation = previous.clone();
            result.nodes = context.nodes;
            result.quiescence_nodes = context.qnodes;
            result.tt_probes = context.tt_probes;
            result.tt_hits = context.tt_hits;
            result.tt_cutoffs = context.tt_cutoffs;
            result.elapsed = start.elapsed();
            reporter(&result);
        }
        return result;
    }
    result.elapsed = start.elapsed();
    reporter(&result);
    result
}

fn repeated(history: &[Position], position: Position) -> bool {
    history.iter().filter(|&&p| p == position).take(3).count() == 3
}
struct Context {
    history: Vec<Position>,
    nodes: u64,
    qnodes: u64,
    table: Option<tt::Table>,
    tt_probes: u64,
    tt_hits: u64,
    tt_cutoffs: u64,
}
impl Context {
    fn new(history: Vec<Position>, limits: SearchLimits) -> Self {
        Self {
            history,
            nodes: 0,
            qnodes: 0,
            table: limits
                .tt_enabled
                .then(|| tt::Table::new(limits.tt_megabytes)),
            tt_probes: 0,
            tt_hits: 0,
            tt_cutoffs: 0,
        }
    }
    fn negamax(
        &mut self,
        position: Position,
        depth: u8,
        ply: u16,
        alpha: i32,
        beta: i32,
        preferred: &[Move],
    ) -> (i32, Vec<Move>) {
        if depth == 0 {
            return self.quiescence(position, ply, alpha, beta);
        }
        self.nodes += 1;
        let mut moves = position.legal_moves();
        if moves.is_empty() {
            return (-MATE + i32::from(ply), Vec::new());
        }
        if repeated(&self.history, position) {
            return (0, Vec::new());
        }
        let clean = tt::clean_history(&self.history);
        let mut tt_move = None;
        if let Some(table) = &self.table {
            self.tt_probes += 1;
            let lookup = table.lookup(position, depth, clean, ply, alpha, beta);
            if lookup.hit {
                self.tt_hits += 1;
            }
            if let Some((score, pv)) = lookup.cutoff {
                self.tt_cutoffs += 1;
                return (score, pv);
            }
            tt_move = lookup.best_move;
        }
        if let Some(first) = tt_move.as_ref() {
            if let Some(index) = moves.iter().position(|mv| mv == first) {
                let mv = moves.remove(index);
                moves.insert(0, mv);
            }
        }
        if let Some(first) = preferred.first() {
            if let Some(index) = moves.iter().position(|mv| mv == first) {
                let mv = moves.remove(index);
                moves.insert(0, mv);
            }
        }
        let original_alpha = alpha;
        let mut alpha = alpha;
        let mut best = -INF;
        let mut pv = Vec::new();
        for mv in moves {
            let child = position.successor(&mv);
            self.history.push(child);
            let next_preferred = if preferred.first() == Some(&mv) {
                &preferred[1..]
            } else {
                &[]
            };
            let (score, continuation) =
                self.negamax(child, depth - 1, ply + 1, -beta, -alpha, next_preferred);
            let score = -score;
            self.history.pop();
            if score > best {
                best = score;
                pv.clear();
                pv.push(mv);
                pv.extend(continuation);
            }
            alpha = alpha.max(best);
            if alpha >= beta {
                break;
            }
        }
        if let Some(table) = &mut self.table {
            let bound = if best <= original_alpha {
                tt::Bound::Upper
            } else if best >= beta {
                tt::Bound::Lower
            } else {
                tt::Bound::Exact
            };
            table.store(position, depth, clean, ply, best, bound, &pv);
        }
        (best, pv)
    }
    fn quiescence(
        &mut self,
        position: Position,
        ply: u16,
        alpha: i32,
        beta: i32,
    ) -> (i32, Vec<Move>) {
        self.nodes += 1;
        self.qnodes += 1;
        let moves = position.legal_moves();
        if moves.is_empty() {
            return (-MATE + i32::from(ply), Vec::new());
        }
        if repeated(&self.history, position) {
            return (0, Vec::new());
        }
        // Legal moves are either all maximal captures or all quiet moves.
        // No stand pat is allowed while capturing. Every capture reduces material,
        // so this tail terminates without an arbitrary tactical depth cutoff.
        if !moves[0].is_capture() {
            return (evaluate(&position), Vec::new());
        }
        let mut alpha = alpha;
        let mut best = -INF;
        let mut pv = Vec::new();
        for mv in moves {
            let child = position.successor(&mv);
            self.history.push(child);
            let (score, continuation) = self.quiescence(child, ply + 1, -beta, -alpha);
            let score = -score;
            self.history.pop();
            if score > best {
                best = score;
                pv.clear();
                pv.push(mv);
                pv.extend(continuation);
            }
            alpha = alpha.max(best);
            if alpha >= beta {
                break;
            }
        }
        (best, pv)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{KingRestriction, Outcome, Piece, Square};
    use Piece::{King, Man};
    use Side::{Black, White};

    fn sq(n: u8) -> Square {
        Square::new(n).unwrap()
    }
    fn position(turn: Side, pieces: &[(u8, Side, Piece)]) -> Position {
        Position::new(
            turn,
            &pieces
                .iter()
                .map(|&(s, c, p)| (sq(s), c, p))
                .collect::<Vec<_>>(),
            [None; 2],
        )
        .unwrap()
    }
    // Exhaustive minimax oracle: no alpha-beta windows or PV ordering.
    fn exhaustive(p: Position, depth: u8, ply: u16, history: &mut Vec<Position>) -> i32 {
        let moves = p.legal_moves();
        if moves.is_empty() {
            return -MATE + i32::from(ply);
        }
        if history.iter().filter(|&&q| q == p).count() >= 3 {
            return 0;
        }
        if depth == 0 && !moves[0].is_capture() {
            return evaluate(&p);
        }
        moves
            .iter()
            .map(|mv| {
                let child = p.successor(mv);
                history.push(child);
                let score = -exhaustive(child, depth.saturating_sub(1), ply + 1, history);
                history.pop();
                score
            })
            .max()
            .unwrap()
    }
    fn context(p: Position) -> Context {
        Context::new(vec![p], SearchLimits::default().with_tt_enabled(false))
    }
    fn replay(game: &Game, pv: &[Move]) {
        let mut copy = game.clone();
        for mv in pv {
            assert_eq!(copy.outcome(), Outcome::Ongoing);
            copy.play(mv).unwrap();
        }
    }
    #[test]
    fn limits_and_fast_paths() {
        assert_eq!(SearchLimits::default().max_depth(), 10);
        assert!(SearchLimits::new(0).is_err());
        assert!(SearchLimits::new(65).is_err());
        assert!(SearchLimits::new(64).is_ok());
        let p = position(White, &[(28, White, Man), (23, Black, Man)]);
        let result = search(&Game::new(p), SearchLimits::default());
        assert!(result.best_move.unwrap().is_capture());
        assert_eq!(result.score, None);
        assert_eq!(result.completed_depth, 0);
        assert_eq!(result.nodes, 0);
        let result = search(
            &Game::new(position(White, &[(1, Black, Man)])),
            SearchLimits::default(),
        );
        assert!(result.best_move.is_none());
        assert_eq!(result.score, Some(-MATE));
    }
    #[test]
    fn alpha_beta_matches_exhaustive_minimax_and_replays_pv() {
        let fixtures = [
            Position::starting(),
            position(
                White,
                &[(28, White, King), (23, Black, Man), (32, Black, Man)],
            ),
            position(
                White,
                &[
                    (11, White, Man),
                    (7, Black, Man),
                    (8, Black, Man),
                    (45, White, Man),
                    (50, Black, King),
                ],
            ),
            position(
                White,
                &[
                    (26, White, Man),
                    (31, White, Man),
                    (1, Black, Man),
                    (16, Black, King),
                ],
            ),
        ];
        for p in fixtures {
            for depth in 1..=3 {
                let expected = exhaustive(p, depth, 0, &mut vec![p]);
                let mut ctx = context(p);
                let (actual, pv) = ctx.negamax(p, depth, 0, -INF, INF, &[]);
                assert_eq!(actual, expected, "depth {depth}, {p:?}");
                replay(&Game::new(p), &pv);
                let game = Game::new(p);
                let before = game.history.clone();
                let result = search(&game, SearchLimits::new(depth).unwrap());
                assert_eq!(game.history, before);
                if p.legal_moves().len() > 1 {
                    assert_eq!(result.score, Some(expected));
                }
                replay(&game, &result.principal_variation);
            }
        }
    }
    #[test]
    fn seeded_positions_match_exhaustive_search() {
        let mut game = Game::default();
        let mut seed = 137u64;
        for _ in 0..32 {
            if game.outcome() != Outcome::Ongoing {
                break;
            }
            let p = *game.position();
            let expected = exhaustive(p, 2, 0, &mut game.history.clone());
            let mut ctx = Context::new(
                game.history.clone(),
                SearchLimits::default().with_tt_enabled(false),
            );
            let (actual, pv) = ctx.negamax(p, 2, 0, -INF, INF, &[]);
            assert_eq!(actual, expected);
            replay(&game, &pv);
            let moves = p.legal_moves();
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            game.play(&moves[seed as usize % moves.len()]).unwrap();
        }
    }
    #[test]
    fn quiescence_follows_forced_material_and_checks_blocked_terminals() {
        let p = position(White, &[(28, White, Man), (23, Black, Man)]);
        let (score, pv) = context(p).quiescence(p, 0, -INF, INF);
        assert_eq!(score, MATE - 1);
        assert_eq!(pv.len(), 1);
        let blocked = position(White, &[(6, White, Man), (1, Black, Man)]);
        assert_eq!(
            context(blocked).quiescence(blocked, 7, -INF, INF).0,
            -MATE + 7
        );
        // Promotion and forced continuation are a complete single move.
        let p = position(White, &[(11, White, Man), (7, Black, Man), (8, Black, Man)]);
        let (score, pv) = context(p).quiescence(p, 0, -INF, INF);
        assert_eq!(score, MATE - 1);
        assert_eq!(pv.len(), 1);
        assert_eq!(pv[0].to(), sq(13));
    }
    #[test]
    fn repetition_uses_existing_history_and_restriction_state() {
        let p = position(White, &[(1, White, King), (5, Black, King)]);
        let mut game = Game::new(p);
        for _ in 0..2 {
            for text in ["1-12", "5-10", "12-1", "10-5"] {
                let mv = game.position().parse_move(text).unwrap();
                game.play(&mv).unwrap();
            }
        }
        let result = search(&game, SearchLimits::new(2).unwrap());
        assert_eq!(result.score, Some(0));
        assert!(result.best_move.is_none());
        let mut ctx = Context::new(
            game.history.clone(),
            SearchLimits::default().with_tt_enabled(false),
        );
        assert_eq!(ctx.negamax(p, 2, 0, -INF, INF, &[]).0, 0);
        assert_eq!(ctx.quiescence(p, 0, -INF, INF).0, 0);
        let p = position(
            White,
            &[(28, White, King), (46, White, Man), (1, Black, Man)],
        );
        let mut q = p;
        q.restrictions[0] = Some(KingRestriction::new(sq(28), 3).unwrap());
        assert!(!repeated(&[p, q, q], p));
        assert!(repeated(&[p, q, p, q, p], p));
    }
    #[test]
    fn search_counts_repetitions_reached_below_root() {
        let p = position(White, &[(1, White, King), (5, Black, King)]);
        let mv = p.parse_move("1-12").unwrap();
        let child = p.successor(&mv);
        let mut ctx = Context::new(
            vec![child, child, p, child],
            SearchLimits::default().with_tt_enabled(false),
        );
        assert_eq!(ctx.negamax(child, 2, 1, -INF, INF, &[]).0, 0);
        assert_ne!(
            context(child).negamax(child, 2, 1, -INF, INF, &[]).0,
            -MATE + 1
        );
    }
    #[test]
    fn evaluator_respects_edges_kings_and_color_symmetry() {
        let make = |n, pc| position(White, &[(n, White, pc), (20, Black, Man)]);
        assert_eq!(evaluate(&make(26, Man)) - evaluate(&make(28, Man)), 8);
        assert_eq!(evaluate(&make(31, Man)) - evaluate(&make(28, Man)), 4);
        assert_eq!(evaluate(&make(26, King)), evaluate(&make(28, King)));
        let p = position(
            White,
            &[(26, White, Man), (28, White, King), (20, Black, Man)],
        );
        let pieces: Vec<_> = (1..=50)
            .filter_map(|n| {
                p.piece_at(sq(n))
                    .map(|(side, pc)| (51 - n, side.other(), pc))
            })
            .collect();
        let mirrored = position(Black, &pieces);
        assert_eq!(evaluate(&p), evaluate(&mirrored));
        let mut opposite = p;
        opposite.turn = Black;
        assert_eq!(evaluate(&p), -evaluate(&opposite));
        let mut q = p;
        q.restrictions[0] = Some(KingRestriction::new(sq(28), 3).unwrap());
        assert_eq!(evaluate(&q), evaluate(&p) - 12);
    }
    #[test]
    fn deterministic_results_include_quiescence_beyond_requested_depth() {
        let game = Game::default();
        let a = search(&game, SearchLimits::new(2).unwrap());
        let b = search(&game, SearchLimits::new(2).unwrap());
        assert_eq!(a.best_move, b.best_move);
        assert_eq!(a.score, b.score);
        assert_eq!(a.principal_variation, b.principal_variation);
        assert_eq!(a.nodes, b.nodes);
        assert_eq!(a.completed_depth, 2);
        assert!(a.quiescence_nodes > 0);
        assert!(a.nodes >= a.quiescence_nodes);
    }
    #[test]
    fn tactical_capture_choices_are_searched_instead_of_first_selected() {
        let mut pieces = Vec::new();
        for n in [
            19, 31, 32, 33, 34, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
        ] {
            pieces.push((n, White, Man));
        }
        for n in [
            1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20,
        ] {
            pieces.push((n, Black, Man));
        }
        let p = position(Black, &pieces);
        let game = Game::new(p);
        assert!(p.legal_moves().len() > 1);
        let r = search(&game, SearchLimits::new(2).unwrap());
        assert_ne!(r.best_move, p.choose_move());
        assert_eq!(r.best_move.unwrap().to_string(), "13x24x19");
        assert_eq!(r.score, Some(exhaustive(p, 2, 0, &mut vec![p])));
        replay(&game, &r.principal_variation);
    }
    #[test]
    fn edge_bonus_cannot_override_a_forced_loss() {
        let p = position(White, &[(31, White, Man), (16, Black, Man)]);
        let edge = p.successor(&p.parse_move("31-26").unwrap());
        let safe = p.successor(&p.parse_move("31-27").unwrap());
        assert!(-evaluate(&edge) > -evaluate(&safe));
        // The edge square is capturable orthogonally. Quiescence sees the loss
        // even at depth 1 and refuses the superficially attractive edge move.
        let result = search(&Game::new(p), SearchLimits::new(1).unwrap());
        assert_eq!(result.best_move.unwrap().to_string(), "31-27");
        assert_eq!(context(edge).quiescence(edge, 1, -INF, INF).0, MATE - 2);
    }
    #[test]
    fn quiescence_pv_extends_beyond_nominal_horizon() {
        let mut found = false;
        let mut game = Game::default();
        let mut seed = 713u64;
        for _ in 0..80 {
            if game.outcome() != Outcome::Ongoing {
                break;
            }
            let r = search(&game, SearchLimits::new(1).unwrap());
            if r.completed_depth == 1 && r.principal_variation.len() > 1 {
                found = true;
                replay(&game, &r.principal_variation);
                break;
            }
            let moves = game.position().legal_moves();
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            game.play(&moves[seed as usize % moves.len()]).unwrap();
        }
        assert!(
            found,
            "capture reply must be searched past the depth-1 horizon"
        );
    }
    #[test]
    fn terminal_scores_prefer_quick_wins_and_delayed_losses() {
        let terminal = position(Black, &[(28, White, King)]);
        let fast_win = -context(terminal).negamax(terminal, 1, 1, -INF, INF, &[]).0;
        let later_win = -context(terminal).negamax(terminal, 1, 5, -INF, INF, &[]).0;
        assert!(fast_win > later_win);
        let early_loss = context(terminal).quiescence(terminal, 1, -INF, INF).0;
        let delayed_loss = context(terminal).quiescence(terminal, 5, -INF, INF).0;
        assert!(delayed_loss > early_loss);
        assert!(fast_win > 15_400); // Outside every possible static material score.
    }
    #[test]
    fn quiet_sacrifice_and_forced_exchange_reach_past_depth_three() {
        let mut pieces = Vec::new();
        for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15, 16] {
            pieces.push((n, Black, Man));
        }
        for n in [
            25, 27, 29, 35, 36, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
        ] {
            pieces.push((n, White, Man));
        }
        let p = position(Black, &pieces);
        let game = Game::new(p);
        let r = search(&game, SearchLimits::new(3).unwrap());
        assert_eq!(r.best_move.unwrap().to_string(), "14-20");
        assert_eq!(r.principal_variation.len(), 4);
        assert_eq!(r.principal_variation[1].to_string(), "25x14x20");
        assert_eq!(r.principal_variation[2].captured().len(), 2);
        assert!(r.principal_variation[3].is_capture());
        assert_eq!(r.score, Some(exhaustive(p, 3, 0, &mut vec![p])));
        replay(&game, &r.principal_variation);
    }
    #[test]
    fn tt_scores_match_uncached_search_and_all_reported_pvs_replay() {
        let mut game = Game::default();
        let mut seed = 3101u64;
        for _ in 0..32 {
            if game.outcome() != Outcome::Ongoing {
                break;
            }
            let mut reports = Vec::new();
            let enabled = search_with_reporter(&game, SearchLimits::new(3).unwrap(), |r| {
                reports.push(r.clone())
            });
            let disabled = search(&game, SearchLimits::new(3).unwrap().with_tt_enabled(false));
            assert_eq!(enabled.score, disabled.score);
            for report in &reports {
                replay(&game, &report.principal_variation);
            }
            if enabled.completed_depth > 0 {
                assert_eq!(reports.len(), 3);
                assert_eq!(
                    reports
                        .iter()
                        .map(|r| r.completed_depth)
                        .collect::<Vec<_>>(),
                    vec![1, 2, 3]
                );
                assert!(reports.windows(2).all(|w| w[0].nodes <= w[1].nodes));
            } else {
                assert_eq!(reports.len(), 1);
            }
            assert_eq!(disabled.tt_probes, 0);
            assert_eq!(disabled.tt_hits, 0);
            assert_eq!(disabled.tt_cutoffs, 0);
            let moves = game.position().legal_moves();
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            game.play(&moves[(seed >> 32) as usize % moves.len()])
                .unwrap();
        }
    }
    #[test]
    fn tt_reuses_scores_and_supports_memory_and_disable_controls() {
        assert!(SearchLimits::new(4).unwrap().tt_enabled());
        assert_eq!(SearchLimits::default().tt_megabytes(), 16);
        assert!(SearchLimits::default().with_tt_megabytes(0).is_err());
        assert!(SearchLimits::default().with_tt_megabytes(257).is_err());
        let limits = SearchLimits::new(6).unwrap().with_tt_megabytes(1).unwrap();
        let game = Game::default();
        let result = search(&game, limits);
        let reference = search(&game, limits.with_tt_enabled(false));
        assert_eq!(result.score, reference.score);
        assert!(result.tt_probes > 0);
        assert!(result.tt_hits > 0);
        assert!(result.tt_cutoffs > 0);
        assert!(result.nodes < reference.nodes);
        replay(&game, &result.principal_variation);
        for game in [
            Game::new(position(White, &[(28, White, Man), (23, Black, Man)])),
            Game::new(position(White, &[(1, Black, Man)])),
        ] {
            let mut reports = Vec::new();
            let r = search_with_reporter(&game, limits, |r| reports.push(r.clone()));
            assert_eq!(reports.len(), 1);
            assert_eq!(reports[0].completed_depth, 0);
            assert_eq!(reports[0].score, r.score);
        }
    }
    #[test]
    fn same_board_different_reversible_histories_never_share_score_cutoffs() {
        let p = position(White, &[(1, White, King), (5, Black, King)]);
        let clean = search(&Game::new(p), SearchLimits::new(4).unwrap());
        let mut game = Game::new(p);
        for text in ["1-12", "5-10", "12-1", "10-5"] {
            let mv = game.position().parse_move(text).unwrap();
            game.play(&mv).unwrap();
        }
        assert_eq!(*game.position(), p);
        assert!(!tt::clean_history(&game.history));
        let cached = search(&game, SearchLimits::new(4).unwrap());
        let uncached = search(&game, SearchLimits::new(4).unwrap().with_tt_enabled(false));
        assert_eq!(cached.score, uncached.score);
        replay(&game, &cached.principal_variation);
        // No man moves or captures occur in the inspected clean king cycle;
        // dirty root history is not discarded simply because the board matches.
        let mut ctx = Context::new(game.history.clone(), SearchLimits::new(4).unwrap());
        let old = clean.principal_variation;
        ctx.table
            .as_mut()
            .unwrap()
            .store(p, 4, true, 0, 1234, tt::Bound::Exact, &old);
        let (score, pv) = ctx.negamax(p, 4, 0, -INF, INF, &[]);
        assert_eq!(score, uncached.score.unwrap());
        assert_ne!(score, 1234);
        replay(&game, &pv);
    }
}
