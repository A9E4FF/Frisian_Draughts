// Validation adapter for Scan 3.1 (GPL-3.0-only).
#include <algorithm>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include "bit.hpp"
#include "fen.hpp"
#include "gen.hpp"
#include "list.hpp"
#include "move.hpp"
#include "pos.hpp"
#include "var.hpp"

static void emit(const Pos &p) {
    std::cout << pos_hub(p);
    for (Side side : {White, Black}) {
        std::cout << ',' << p.count(side) << ':';
        if (p.count(side)) std::cout << square_to_std(p.wolf(side));
        else std::cout << 0;
    }
    List list;
    gen_moves(list, p);
    std::vector<std::string> moves;
    for (Move mv : list) moves.push_back(move::to_hub(mv,p));
    std::sort(moves.begin(), moves.end());
    moves.erase(std::unique(moves.begin(),moves.end()),moves.end());
    std::cout << '|';
    for (auto &m : moves) std::cout << m << ' ';
    std::cout << std::endl;
}
int main() {
    var::init();
    var::set("variant","frisian");
    var::update();
    bit::init(); pos::init();
    Pos p=pos::Start;
    std::string line;
    while (std::getline(std::cin,line)) {
        std::istringstream input(line);
        std::string command,arg;
        input>>command>>arg;
        if (command=="new") p=pos_from_hub(arg);
        else if (command=="play") {
            Move mv=move::from_hub(arg,p);
            if (!move::is_legal(mv,p)) return 2;
            p=p.succ(mv);
        } else return 3;
        emit(p);
    }
}
