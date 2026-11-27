#include "render/sfml_renderer.hpp"

#include <sstream>
#include <iomanip>
#include <stdexcept>
#include <cstdint>
#include <cmath>

namespace {
// --- boundary conversions: core types -> SFML types ---
inline sf::Vector2f sfVec(const Vec2& v) { return {v.x, v.y}; }
inline sf::Color    sfColor(const Color& c) { return {c.r, c.g, c.b, c.a}; }
} // namespace

SfmlRenderer::SfmlRenderer(int width, int height, const std::string& title)
    : window_(sf::VideoMode(width, height), title) {
    window_.setPosition({0, 0});
    window_.setVerticalSyncEnabled(false);
    window_.setFramerateLimit(0);

    if (!circleTexture_.loadFromFile("img/circle.png")) {
        throw std::runtime_error("Failed to load img/circle.png");
    }

    hasBg_ = bgTexture_.loadFromFile("img/rocks.jpg");
    if (hasBg_) bgSprite_.setTexture(bgTexture_);

    hasFont_ = font_.loadFromFile("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf") ||
               font_.loadFromFile("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf");
}

bool SfmlRenderer::isOpen() const {
    return window_.isOpen();
}

float SfmlRenderer::frameDelta() {
    return frameClock_.restart().asSeconds();
}

InputEvents SfmlRenderer::poll() {
    InputEvents ev;

    sf::Event event;
    while (window_.pollEvent(event)) {
        if (event.type == sf::Event::Closed) {
            window_.close();
            ev.quit = true;
        } else if (event.type == sf::Event::MouseButtonPressed &&
                   event.mouseButton.button == sf::Mouse::Left) {
            // Defer hit-testing to render(), which has the World to test against.
            hasPendingClick_ = true;
            clickX_ = event.mouseButton.x;
            clickY_ = event.mouseButton.y;
        }
    }

    // Space -> toggle pause (rising edge only)
    bool space = sf::Keyboard::isKeyPressed(sf::Keyboard::Space);
    if (space && !spaceWasPressed_) ev.togglePause = true;
    spaceWasPressed_ = space;

    // Up / Down -> change sim speed (rising edge only)
    bool up = sf::Keyboard::isKeyPressed(sf::Keyboard::Up);
    if (up && !upWasPressed_) ev.speedUp = true;
    upWasPressed_ = up;

    bool down = sf::Keyboard::isKeyPressed(sf::Keyboard::Down);
    if (down && !downWasPressed_) ev.speedDown = true;
    downWasPressed_ = down;

    // T -> toggle headless burst (turbo); S -> save a checkpoint (rising edge)
    bool t = sf::Keyboard::isKeyPressed(sf::Keyboard::T);
    if (t && !tWasPressed_) ev.toggleTurbo = true;
    tWasPressed_ = t;

    bool s = sf::Keyboard::isKeyPressed(sf::Keyboard::S);
    if (s && !sWasPressed_) ev.saveCheckpoint = true;
    sWasPressed_ = s;

    return ev;
}

void SfmlRenderer::render(const World& world, const HudInfo& hud) {
    window_.clear(sf::Color(15, 30, 25));
    if (hasBg_) window_.draw(bgSprite_);

    if (world.currentActive()) drawCurrentField(world);   // flow under everything
    drawFood(world.food);
    drawCreatures(world.creatures);
    drawPredators(world.predators);                       // on top of prey

    // Live neural inspector: resolve any click to a creature, ring it, and draw
    // its net firing in the top-right panel (drawn last so it sits above the HUD).
    resolveSelection(world);
    if (const Creature* sel = findSelected(world)) {
        drawSelectionRing(*sel);
        drawHud(hud);
        drawNeuralOverlay(*sel);
    } else {
        drawHud(hud);
    }

    window_.display();
}

void SfmlRenderer::drawCreatures(const std::vector<Creature>& creatures) {
    // Count total quads needed
    int totalQuads = 0;
    for (const auto& c : creatures) {
        (void)c;
        totalQuads += Creature::BODY_LEN;
    }

    sf::VertexArray va(sf::Quads, totalQuads * 4);
    const float texSize = 1024.0f;
    int idx = 0;

    // Segment radius scales with the heritable bodySize (the same formula
    // web/renderer.js bodyScale() uses — the two frontends must look alike).
    // bodySize is core-clamped to [0.5, 2] but its realised standing spread is
    // narrow (sd ~0.08 about 1.0), so a plain multiply would separate two
    // typical neighbours by a couple of tenths of a pixel. tanh gives slope
    // kBodySpan*kBodyGain = 2 where the population actually sits and saturates
    // at +/-kBodySpan, so the rails stay sane: a 2.0 body draws 1.4x, not 2x.
    // tanh(0) is exactly 0, so a default 1.0 body multiplies by exactly 1 and
    // the pre-body-model picture is unchanged. kMinRadius keeps the tail
    // segment of a small body visible.
    const float kBodyGain = 5.0f, kBodySpan = 0.4f, kMinRadius = 1.0f;

    for (const auto& c : creatures) {
        const float bodyScale = 1.0f + kBodySpan * std::tanh(kBodyGain * (c.bodySize - 1.0f));
        for (int s = 0; s < Creature::BODY_LEN; ++s) {
            float rad = (s == 0) ? 5.0f : 4.0f - s * 0.5f;
            if (rad < 1.5f) rad = 1.5f;
            rad *= bodyScale;
            if (rad < kMinRadius) rad = kMinRadius;

            float px = c.body[s].x;
            float py = c.body[s].y;

            // Fade color along body
            sf::Color segColor = sfColor(c.color);
            segColor.a = static_cast<uint8_t>(255 - s * 30);

            va[idx + 0].position = {px - rad, py - rad};
            va[idx + 1].position = {px + rad, py - rad};
            va[idx + 2].position = {px + rad, py + rad};
            va[idx + 3].position = {px - rad, py + rad};

            va[idx + 0].texCoords = {0, 0};
            va[idx + 1].texCoords = {texSize, 0};
            va[idx + 2].texCoords = {texSize, texSize};
            va[idx + 3].texCoords = {0, texSize};

            va[idx + 0].color = segColor;
            va[idx + 1].color = segColor;
            va[idx + 2].color = segColor;
            va[idx + 3].color = segColor;

            idx += 4;
        }
    }

    sf::RenderStates states;
    states.texture = &circleTexture_;
    window_.draw(va, states);
}

// Faint flow-field overlay: short line segments sampled on a coarse grid, each
// pointing along the local current with length proportional to flow speed.
// (Drawn under food/creatures so it reads as background.)
void SfmlRenderer::drawCurrentField(const World& world) {
    const int   step = 64;     // grid spacing in pixels
    const float vis  = 0.45f;  // seconds of flow drawn per segment
    sf::VertexArray va(sf::Lines);
    const sf::Color tail(110, 170, 215, 60);
    const sf::Color head(150, 205, 235, 130);
    for (int y = step / 2; y < world.height; y += step) {
        for (int x = step / 2; x < world.width; x += step) {
            Vec2 v = world.currentAt(Vec2{(float)x, (float)y});
            if (v.x * v.x + v.y * v.y < 1.0f) continue;
            va.append(sf::Vertex(sf::Vector2f((float)x, (float)y), tail));
            va.append(sf::Vertex(sf::Vector2f(x + v.x * vis, y + v.y * vis), head));
        }
    }
    window_.draw(va);
}

void SfmlRenderer::drawFood(const std::vector<Food>& food) {
    sf::VertexArray va(sf::Quads, food.size() * 4);
    const float texSize = 1024.0f;
    const float rad = 2.5f;
    sf::Color foodColor(151, 198, 50);

    for (size_t i = 0; i < food.size(); ++i) {
        int idx = static_cast<int>(i) * 4;
        float px = food[i].pos.x;
        float py = food[i].pos.y;

        va[idx + 0].position = {px - rad, py - rad};
        va[idx + 1].position = {px + rad, py - rad};
        va[idx + 2].position = {px + rad, py + rad};
        va[idx + 3].position = {px - rad, py + rad};

        va[idx + 0].texCoords = {0, 0};
        va[idx + 1].texCoords = {texSize, 0};
        va[idx + 2].texCoords = {texSize, texSize};
        va[idx + 3].texCoords = {0, texSize};

        va[idx + 0].color = foodColor;
        va[idx + 1].color = foodColor;
        va[idx + 2].color = foodColor;
        va[idx + 3].color = foodColor;
    }

    sf::RenderStates states;
    states.texture = &circleTexture_;
    window_.draw(va, states);
}

// Predators (Stage A): one filled disc per predator, drawn in red and a touch
// larger than prey so they read as the threat. Reuses the same textured-quad
// pattern as drawFood/drawCreatures (a digesting predator is dimmed slightly).
void SfmlRenderer::drawPredators(const std::vector<Predator>& predators) {
    if (predators.empty()) return;

    sf::VertexArray va(sf::Quads, predators.size() * 4);
    const float texSize = 1024.0f;
    const float rad = 6.5f;

    for (size_t i = 0; i < predators.size(); ++i) {
        int idx = static_cast<int>(i) * 4;
        float px = predators[i].pos.x;
        float py = predators[i].pos.y;

        sf::Color col(220, 50, 50);
        if (predators[i].digestTimer > 0.0f) col = sf::Color(150, 60, 60);  // digesting

        va[idx + 0].position = {px - rad, py - rad};
        va[idx + 1].position = {px + rad, py - rad};
        va[idx + 2].position = {px + rad, py + rad};
        va[idx + 3].position = {px - rad, py + rad};

        va[idx + 0].texCoords = {0, 0};
        va[idx + 1].texCoords = {texSize, 0};
        va[idx + 2].texCoords = {texSize, texSize};
        va[idx + 3].texCoords = {0, texSize};

        va[idx + 0].color = col;
        va[idx + 1].color = col;
        va[idx + 2].color = col;
        va[idx + 3].color = col;
    }

    sf::RenderStates states;
    states.texture = &circleTexture_;
    window_.draw(va, states);
}

void SfmlRenderer::drawHud(const HudInfo& hud) {
    if (!hasFont_) return;

    std::ostringstream out;
    out << "Pop: " << hud.population
        << "  Food: " << hud.food;
    if (hud.predators > 0) out << "  Pred: " << hud.predators;
    out << "  Frame: " << hud.frame
        << "  Births: " << hud.births
        << "  Deaths: " << hud.deaths
        << "  AvgGenome: " << std::fixed << std::setprecision(1) << hud.avgGenome
        << "  Gen: " << hud.genMax << " (avg " << hud.genMean << ")"
        << "  Speed: " << hud.simSpeed << "x"
        << "  FPS: " << hud.fps;
    if (hud.paused) out << "  [PAUSED]";
    if (hud.turbo)
        out << "  [TURBO " << std::setprecision(0) << hud.stepsPerSec << " steps/s]";
    out << "\n[Space] pause  [Up/Down] speed  [T] turbo  [S] save checkpoint";

    sf::Text text(out.str(), font_, 14);
    text.setFillColor(sf::Color(200, 200, 200, 200));
    text.setPosition(10, 10);
    window_.draw(text);
}

// ============================================================
// Live neural inspector (click a fish -> watch its net fire)
// ============================================================
namespace {

// Diverging activation colour: negative -> blue, ~0 -> dim grey, positive -> red.
// Brightness scales with magnitude so a "firing" node is vivid, an idle one dim.
inline sf::Color activationColor(float v, uint8_t alpha = 255) {
    const float m = std::min(1.0f, std::fabs(v));
    const int lo = 45;                       // idle floor (never pure black)
    const int hot = lo + (int)std::lround((235 - lo) * m);
    if (v >= 0.0f) return sf::Color((uint8_t)hot, (uint8_t)(lo + (60 * (1 - m))), (uint8_t)lo, alpha);
    return sf::Color((uint8_t)lo, (uint8_t)(lo + (90 * (1 - m))), (uint8_t)hot, alpha);
}

const char* actionName(int a) {
    switch (a) {
        case STEER_X: return "steerX"; case STEER_Y: return "steerY";
        case MOVE_FORWARD: return "moveFwd"; case MOVE_RANDOM: return "moveRnd";
        case SPEED_ADJUST: return "speed"; case EMIT_SIGNAL0: return "signal";
        case SET_OSCILLATOR_PERIOD: return "oscPer"; case SET_RESPONSIVENESS: return "resp";
        case INTERACT_SHARE: return "share"; case INTERACT_REPRODUCE: return "repro";
        case INTERACT_FIGHT: return "fight"; case INTERACT_IGNORE: return "ignore";
        default: return "?";
    }
}

}  // namespace

void SfmlRenderer::resolveSelection(const World& world) {
    if (!hasPendingClick_) return;
    hasPendingClick_ = false;

    const sf::Vector2f w = window_.mapPixelToCoords(sf::Vector2i(clickX_, clickY_));
    const float pickR2 = 25.0f * 25.0f;       // pick radius in world units
    float bestD2 = pickR2;
    std::uint64_t best = 0;
    for (const Creature& c : world.creatures) {
        const float dx = c.pos.x - w.x, dy = c.pos.y - w.y;
        const float d2 = dx * dx + dy * dy;
        if (d2 < bestD2) { bestD2 = d2; best = c.id; }
    }
    selectedId_ = best;                       // 0 (deselect) if nothing close
}

const Creature* SfmlRenderer::findSelected(const World& world) const {
    if (selectedId_ == 0) return nullptr;
    for (const Creature& c : world.creatures)
        if (c.id == selectedId_) return &c;
    return nullptr;                            // selected fish has since died
}

void SfmlRenderer::drawSelectionRing(const Creature& c) {
    sf::CircleShape ring(16.0f);
    ring.setOrigin(16.0f, 16.0f);
    ring.setPosition(c.pos.x, c.pos.y);
    ring.setFillColor(sf::Color(0, 0, 0, 0));
    ring.setOutlineThickness(2.0f);
    ring.setOutlineColor(sf::Color(255, 235, 120, 230));
    window_.draw(ring);
}

// Translucent top-right board: sensors (left col) -> hidden neurons (mid) ->
// actions (right col). Connections are tinted by weight*source-activity so the
// live signal flow is visible; node fill is the node's current activation.
void SfmlRenderer::drawNeuralOverlay(const Creature& c) {
    const float winW = (float)window_.getSize().x;
    const float panelW = 340.0f, margin = 12.0f;
    const float panelX = (winW > panelW + margin ? winW - panelW - margin : margin);
    const float panelY = 44.0f;                // below the HUD line
    const float panelH = 560.0f;

    // Panel background (translucent).
    sf::RectangleShape panel(sf::Vector2f(panelW, panelH));
    panel.setPosition(panelX, panelY);
    panel.setFillColor(sf::Color(10, 22, 30, 205));
    panel.setOutlineThickness(1.0f);
    panel.setOutlineColor(sf::Color(90, 140, 150, 220));
    window_.draw(panel);

    const float xSensor = panelX + 30.0f;
    const float xHidden = panelX + panelW * 0.5f;
    const float xAction = panelX + panelW - 30.0f;
    const float yTop = panelY + 46.0f;
    const float yBot = panelY + panelH - 22.0f;

    auto colY = [&](int i, int n) {
        return (n <= 1) ? (yTop + yBot) * 0.5f
                        : yTop + (yBot - yTop) * (float)i / (float)(n - 1);
    };
    auto sensorPos = [&](int i) { return sf::Vector2f(xSensor, colY(i, NUM_SENSES)); };
    auto hiddenPos = [&](int i) { return sf::Vector2f(xHidden, colY(i, MAX_INTERNAL_NEURONS)); };
    auto actionPos = [&](int i) { return sf::Vector2f(xAction, colY(i, NUM_ACTIONS)); };

    const sf::Vector2f biasPos(xHidden, panelY + 24.0f);
    bool hasBias = false;
    // 1) Connections first (under the nodes). Alpha ~ |weight|*|source activation|.
    sf::VertexArray links(sf::Lines);
    for (const auto& fc : c.nnet.flat) {
        const Gene g = asGene(fc);
        const bool bias = fc.logCodec() && g.sourceType == SOURCE_NEURON && g.sourceNum == 127;
        hasBias |= bias;
        sf::Vector2f a = (g.sourceType == SOURCE_SENSOR) ? sensorPos(g.sourceNum)
                                                         : (bias ? biasPos : hiddenPos(g.sourceNum));
        sf::Vector2f b = (g.sinkType == SINK_ACTION) ? actionPos(g.sinkNum)
                                                     : hiddenPos(g.sinkNum);
        const float srcAct = (g.sourceType == SOURCE_SENSOR)
                             ? c.lastSensors[g.sourceNum]
                             : (bias ? 1.0f : c.nnet.neurons[g.sourceNum].output);
        const float w = fc.w();
        const float mag = std::min(1.0f, std::fabs(w) * std::fabs(srcAct) * 1.5f);
        const uint8_t alpha = (uint8_t)(25 + std::lround(180 * mag));
        const sf::Color col = (w >= 0.0f) ? sf::Color(120, 200, 130, alpha)
                                          : sf::Color(210, 120, 120, alpha);
        links.append(sf::Vertex(a, col));
        links.append(sf::Vertex(b, col));
    }
    window_.draw(links);

    // 2) Nodes, coloured by current activation.
    auto drawNode = [&](sf::Vector2f p, float act, float r) {
        sf::CircleShape dot(r);
        dot.setOrigin(r, r);
        dot.setPosition(p);
        dot.setFillColor(activationColor(act));
        dot.setOutlineThickness(0.5f);
        dot.setOutlineColor(sf::Color(0, 0, 0, 160));
        window_.draw(dot);
    };
    for (int i = 0; i < NUM_SENSES; ++i)            drawNode(sensorPos(i), c.lastSensors[i], 3.0f);
    for (int i = 0; i < MAX_INTERNAL_NEURONS; ++i)  drawNode(hiddenPos(i), c.nnet.neurons[i].output, 5.0f);
    for (int i = 0; i < NUM_ACTIONS; ++i)           drawNode(actionPos(i), c.lastActions[i], 5.0f);

    if (hasBias) drawNode(biasPos, 1.0f, 5.0f);
    // 3) Labels (title + action names) when a font is available.
    if (hasFont_) {
        if (hasBias) {
            sf::Text label("+1", font_, 11);
            label.setPosition(biasPos.x + 6.0f, biasPos.y - 6.0f);
            window_.draw(label);
        }
        std::ostringstream title;
        title << "Fish #" << c.id
              << "   spd " << std::fixed << std::setprecision(0) << c.speed
              << "   E " << std::setprecision(0) << c.foodReserves
              << "   age " << std::setprecision(0) << c.age;
        sf::Text t(title.str(), font_, 13);
        t.setFillColor(sf::Color(220, 235, 240, 235));
        t.setPosition(panelX + 12.0f, panelY + 8.0f);
        window_.draw(t);

        // Body params on their own line at the panel foot — appended to the
        // title they would run past the 340px panel. Always drawn, so a run
        // with the body model off reads as a fixed 1.00 / 1.00 rather than as
        // a missing field. Mirrors the web inspector.
        std::ostringstream body;
        body << "body " << std::fixed << std::setprecision(2) << c.bodySize
             << "   elong " << c.bodyElong
             << "   gen " << c.generation;
        sf::Text bt(body.str(), font_, 11);
        bt.setFillColor(sf::Color(190, 205, 210, 220));
        bt.setPosition(panelX + 12.0f, panelY + panelH - 20.0f);
        window_.draw(bt);

        sf::Text colhdr("in", font_, 11);
        colhdr.setFillColor(sf::Color(150, 175, 180, 200));
        colhdr.setPosition(xSensor - 8.0f, yTop - 18.0f); window_.draw(colhdr);
        colhdr.setString("hidden"); colhdr.setPosition(xHidden - 20.0f, yTop - 18.0f); window_.draw(colhdr);
        colhdr.setString("out");    colhdr.setPosition(xAction - 12.0f, yTop - 18.0f); window_.draw(colhdr);

        for (int i = 0; i < NUM_ACTIONS; ++i) {
            sf::Text lbl(actionName(i), font_, 10);
            lbl.setFillColor(sf::Color(190, 205, 210, 220));
            lbl.setPosition(xAction + 8.0f, colY(i, NUM_ACTIONS) - 6.0f);
            window_.draw(lbl);
        }
    }
}
