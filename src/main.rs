use frisian_draughts::{Game, Outcome, Side};
use std::io::{self, Write};

fn engine(game: &mut Game) {
    if let Some(mv) = game.choose_move() {
        println!("Engine: {mv}");
        game.play(&mv).expect("selected legal move");
    }
}
fn main() -> io::Result<()> {
    let mut game = Game::default();
    let mut checkpoints = Vec::new();
    println!(
        "Frisian Draughts — you are White. Type help for commands.\n{}",
        game.position()
    );
    loop {
        print!("> ");
        io::stdout().flush()?;
        let mut input = String::new();
        if io::stdin().read_line(&mut input)? == 0 {
            break;
        }
        let input = input.trim();
        match input {
            "quit"=>break,
            "help"=>println!("board | moves | play <move> | go | undo | new | quit\nMoves: 32-28 or 32x23; ambiguous captures need the displayed captured-square suffix.\nw/b: men, W/B: kings. Engine plays Black automatically. No search."),
            "board"=>println!("{}",game.position()),
            "moves"=>println!("{}",game.position().legal_moves().iter().map(ToString::to_string).collect::<Vec<_>>().join(" ")),
            "new"=>{game=Game::default(); checkpoints.clear(); println!("{}",game.position());},
            "undo"=>{
                if let Some(ply)=checkpoints.pop() {game.undo_to(ply).unwrap(); println!("{}",game.position());}
                else {println!("Nothing to undo");}
            },
            "go"=>{
                if game.outcome()==Outcome::Ongoing {checkpoints.push(game.ply()); engine(&mut game); println!("{}",game.position());}
            },
            _=>{
                if let Some(text)=input.strip_prefix("play ") {
                    let ply=game.ply();
                    match game.position().parse_move(text).and_then(|mv|game.play(&mv)) {
                        Ok(())=>{
                            checkpoints.push(ply);
                            if game.position().turn()==Side::Black {engine(&mut game);}
                            println!("{}",game.position());
                        },
                        Err(e)=>println!("Error: {e}"),
                    }
                } else {println!("Unknown command; type help");}
            }
        }
        match game.outcome() {
            Outcome::Ongoing => {}
            Outcome::Won(side) => println!("{side:?} wins"),
            Outcome::Draw => println!("Draw by threefold repetition"),
        }
    }
    Ok(())
}
