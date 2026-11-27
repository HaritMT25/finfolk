#include "ocean/ocean_world.hpp"
#include "genome_v2_test_helpers.hpp"
int main() {
    Genome g{g2Gene(0,127,1,0,16385), g2Gene(1,1,0,0,0), g2Gene(0,0,1,1,1)};
    g.schema={2,true}; NeuralNet n;
    G2_CHECK(buildNeuralNet(g,n),"reach build");
    G2_CHECK(!ocean::sensorReachesAction(n,0,0),"bias reach bounded");
    G2_CHECK(ocean::sensorReachesAction(n,1,1),"sensor hidden reach");
    std::puts("genome v2 reach: all assertions passed");
}
