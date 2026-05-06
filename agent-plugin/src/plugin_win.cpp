// Agent UI CLAP Plugin – Windows version
// Embeds Prompt/Response UI in Bitwig's device panel (Win32 HWND child window).
// Communicates with Python agent via OSC (UDP 127.0.0.1:9003/9004).

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <clap/clap.h>
#include <clap/ext/gui.h>
#include <clap/ext/state.h>
#include <clap/ext/timer-support.h>

#include "osc_win.h"
#include "ui_win.h"

#include <cstring>
#include <memory>
#include <string>
#include <mutex>
#include <atomic>

// ── constants ─────────────────────────────────────────────────────────────────
static constexpr char PLUGIN_ID[]   = "com.bitwigagent.agent-ui";
static constexpr char PLUGIN_NAME[] = "Agent UI";
static constexpr char PLUGIN_VER[]  = "1.0.0";
static constexpr char VENDOR[]      = "BitwigAgent";
static constexpr char URL[]         = "";
static constexpr char MANUAL[]      = "";
static constexpr char SUPPORT[]     = "";
static constexpr char DESC[]        = "AI Agent Prompt/Response panel";

static constexpr int AGENT_OSC_PORT      = 9003;
static constexpr int AGENT_RESPONSE_PORT = 9004;
static constexpr clap_id TIMER_ID        = 1;
static constexpr uint32_t TIMER_MS       = 100;

static HINSTANCE g_hInst = nullptr;

// ── plugin data ───────────────────────────────────────────────────────────────
struct AgentPlugin {
    const clap_host_t*               host{};
    const clap_host_gui_t*           host_gui{};
    const clap_host_timer_support_t* host_timer{};

    std::unique_ptr<OscSender>   sender;
    std::unique_ptr<OscReceiver> receiver;

    AgentUI ui;
    bool    gui_created{false};

    std::mutex  response_mutex;
    std::string pending_response;
    std::atomic<bool> has_pending{false};

    void on_osc_message(const std::string& path, const std::string& value) {
        if (path == "/agent/ui/response") {
            std::lock_guard<std::mutex> lk(response_mutex);
            pending_response = value;
            has_pending = true;
        }
    }

    void on_send(const std::string& prompt) {
        if (sender) sender->send_string("/agent/ui/prompt", prompt.c_str());
        ui.set_response("Sending…");
    }

    void tick() {
        if (has_pending.exchange(false)) {
            std::string resp;
            {
                std::lock_guard<std::mutex> lk(response_mutex);
                resp = std::move(pending_response);
            }
            ui.set_response(resp);
            ui.clear_prompt();
        }
    }
};

static AgentPlugin* get(const clap_plugin_t* p) {
    return static_cast<AgentPlugin*>(p->plugin_data);
}

// ── lifecycle ─────────────────────────────────────────────────────────────────
static bool plugin_init(const clap_plugin_t* p) {
    auto* ap = get(p);
    ap->host_gui   = static_cast<const clap_host_gui_t*>(
        ap->host->get_extension(ap->host, CLAP_EXT_GUI));
    ap->host_timer = static_cast<const clap_host_timer_support_t*>(
        ap->host->get_extension(ap->host, CLAP_EXT_TIMER_SUPPORT));

    ap->sender   = std::make_unique<OscSender>("127.0.0.1", AGENT_OSC_PORT);
    ap->receiver = std::make_unique<OscReceiver>(
        AGENT_RESPONSE_PORT,
        [ap](const std::string& path, const std::string& val) {
            ap->on_osc_message(path, val);
        });
    return true;
}

static void plugin_destroy(const clap_plugin_t* p) {
    auto* ap = get(p);
    if (ap->host_timer && ap->host_timer->unregister_timer)
        ap->host_timer->unregister_timer(ap->host, TIMER_ID);
    ap->receiver.reset();
    ap->sender.reset();
    delete ap;
}

static bool plugin_activate(const clap_plugin_t*, double, uint32_t, uint32_t) { return true; }
static void plugin_deactivate(const clap_plugin_t*) {}
static bool plugin_start_processing(const clap_plugin_t*) { return true; }
static void plugin_stop_processing(const clap_plugin_t*) {}
static void plugin_reset(const clap_plugin_t*) {}

static clap_process_status plugin_process(const clap_plugin_t*, const clap_process_t* proc) {
    if (proc->audio_outputs_count > 0 && proc->audio_inputs_count > 0) {
        auto& in  = proc->audio_inputs[0];
        auto& out = proc->audio_outputs[0];
        uint32_t ch = min(in.channel_count, out.channel_count);
        for (uint32_t c = 0; c < ch; ++c)
            memcpy(out.data32[c], in.data32[c], proc->frames_count * sizeof(float));
    }
    return CLAP_PROCESS_CONTINUE;
}

static void plugin_on_main_thread(const clap_plugin_t*) {}

// ── GUI extension ─────────────────────────────────────────────────────────────
static bool gui_is_api_supported(const clap_plugin_t*, const char* api, bool floating) {
    return !floating && strcmp(api, CLAP_WINDOW_API_WIN32) == 0;
}

static bool gui_get_preferred_api(const clap_plugin_t*, const char** api, bool* floating) {
    *api     = CLAP_WINDOW_API_WIN32;
    *floating = false;
    return true;
}

static bool gui_create(const clap_plugin_t* p, const char* api, bool floating) {
    if (floating || strcmp(api, CLAP_WINDOW_API_WIN32) != 0) return false;
    auto* ap = get(p);
    ap->gui_created = true;
    return true;
}

static void gui_destroy(const clap_plugin_t* p) {
    auto* ap = get(p);
    if (!ap->gui_created) return;
    ap->ui.destroy();
    ap->gui_created = false;
}

static bool gui_set_scale(const clap_plugin_t*, double) { return true; }

static bool gui_get_size(const clap_plugin_t*, uint32_t* w, uint32_t* h) {
    *w = AgentUI::W;
    *h = AgentUI::H;
    return true;
}

static bool gui_can_resize(const clap_plugin_t*) { return true; }

static bool gui_get_resize_hints(const clap_plugin_t*, clap_gui_resize_hints_t* hints) {
    hints->can_resize_horizontally = true;
    hints->can_resize_vertically   = true;
    hints->preserve_aspect_ratio   = false;
    return true;
}

static bool gui_adjust_size(const clap_plugin_t*, uint32_t* w, uint32_t* h) {
    *w = max(*w, 300u);
    *h = max(*h, 150u);
    return true;
}

static bool gui_set_size(const clap_plugin_t* p, uint32_t w, uint32_t h) {
    get(p)->ui.set_size((int)w, (int)h);
    return true;
}

static bool gui_set_parent(const clap_plugin_t* p, const clap_window_t* window) {
    auto* ap = get(p);
    if (!ap->gui_created) return false;
    HWND parent = static_cast<HWND>(window->win32);
    bool ok = ap->ui.create(parent, g_hInst);
    if (!ok) return false;
    ap->ui.on_send = [ap](const std::string& prompt) { ap->on_send(prompt); };
    if (ap->host_timer && ap->host_timer->register_timer)
        ap->host_timer->register_timer(ap->host, TIMER_MS, const_cast<clap_id*>(&TIMER_ID));
    return true;
}

static bool gui_set_transient(const clap_plugin_t*, const clap_window_t*) { return false; }
static void gui_suggest_title(const clap_plugin_t*, const char*) {}

static bool gui_show(const clap_plugin_t* p) {
    auto* ap = get(p);
    if (ap->ui.win) ShowWindow(ap->ui.win, SW_SHOW);
    return true;
}

static bool gui_hide(const clap_plugin_t* p) {
    auto* ap = get(p);
    if (ap->ui.win) ShowWindow(ap->ui.win, SW_HIDE);
    return true;
}

static const clap_plugin_gui_t s_gui = {
    .is_api_supported  = gui_is_api_supported,
    .get_preferred_api = gui_get_preferred_api,
    .create            = gui_create,
    .destroy           = gui_destroy,
    .set_scale         = gui_set_scale,
    .get_size          = gui_get_size,
    .can_resize        = gui_can_resize,
    .get_resize_hints  = gui_get_resize_hints,
    .adjust_size       = gui_adjust_size,
    .set_size          = gui_set_size,
    .set_parent        = gui_set_parent,
    .set_transient     = gui_set_transient,
    .suggest_title     = gui_suggest_title,
    .show              = gui_show,
    .hide              = gui_hide,
};

// ── Timer ─────────────────────────────────────────────────────────────────────
static void timer_on_timer(const clap_plugin_t* p, clap_id timer_id) {
    if (timer_id == TIMER_ID) get(p)->tick();
}

static const clap_plugin_timer_support_t s_timer = {
    .on_timer = timer_on_timer,
};

// ── State support ─────────────────────────────────────────────────────────────
static bool state_save(const clap_plugin_t*, const clap_ostream_t* stream) {
    if (!stream || !stream->write) return false;
    const uint32_t version = 1;
    const int64_t written = stream->write(stream, &version, sizeof(version));
    return written == (int64_t)sizeof(version);
}

static bool state_load(const clap_plugin_t*, const clap_istream_t* stream) {
    if (!stream || !stream->read) return false;
    uint32_t version = 0;
    const int64_t n = stream->read(stream, &version, sizeof(version));
    // Empty state is treated as valid default state.
    if (n == 0) return true;
    return n == (int64_t)sizeof(version);
}

static const clap_plugin_state_t s_state = {
    .save = state_save,
    .load = state_load,
};

// ── extension dispatch ────────────────────────────────────────────────────────
static const void* plugin_get_extension(const clap_plugin_t*, const char* id) {
    if (strcmp(id, CLAP_EXT_GUI) == 0)           return &s_gui;
    if (strcmp(id, CLAP_EXT_TIMER_SUPPORT) == 0) return &s_timer;
    if (strcmp(id, CLAP_EXT_STATE) == 0)         return &s_state;
    return nullptr;
}

// ── descriptor ────────────────────────────────────────────────────────────────
static const char* s_features[] = {
    CLAP_PLUGIN_FEATURE_UTILITY,
    nullptr,
};

static const clap_plugin_descriptor_t s_desc = {
    .clap_version = CLAP_VERSION_INIT,
    .id           = PLUGIN_ID,
    .name         = PLUGIN_NAME,
    .vendor       = VENDOR,
    .url          = URL,
    .manual_url   = MANUAL,
    .support_url  = SUPPORT,
    .version      = PLUGIN_VER,
    .description  = DESC,
    .features     = s_features,
};

// ── factory ───────────────────────────────────────────────────────────────────
static const clap_plugin_t* factory_create(const clap_plugin_factory_t*,
                                           const clap_host_t* host,
                                           const char* plugin_id) {
    if (strcmp(plugin_id, PLUGIN_ID) != 0) return nullptr;
    auto* ap     = new AgentPlugin();
    ap->host     = host;
    auto* plugin        = new clap_plugin_t{};
    plugin->desc        = &s_desc;
    plugin->plugin_data = ap;
    plugin->init        = plugin_init;
    plugin->destroy     = plugin_destroy;
    plugin->activate    = plugin_activate;
    plugin->deactivate  = plugin_deactivate;
    plugin->start_processing = plugin_start_processing;
    plugin->stop_processing  = plugin_stop_processing;
    plugin->reset       = plugin_reset;
    plugin->process     = plugin_process;
    plugin->get_extension    = plugin_get_extension;
    plugin->on_main_thread   = plugin_on_main_thread;
    return plugin;
}

static uint32_t factory_count(const clap_plugin_factory_t*) { return 1; }
static const clap_plugin_descriptor_t* factory_desc(const clap_plugin_factory_t*, uint32_t) {
    return &s_desc;
}

static const clap_plugin_factory_t s_factory = {
    .get_plugin_count      = factory_count,
    .get_plugin_descriptor = factory_desc,
    .create_plugin         = factory_create,
};

// ── CLAP entry ────────────────────────────────────────────────────────────────
static bool entry_init(const char*) { return true; }
static void entry_deinit()          {}
static const void* entry_get_factory(const char* fid) {
    if (strcmp(fid, CLAP_PLUGIN_FACTORY_ID) == 0) return &s_factory;
    return nullptr;
}

extern "C" __declspec(dllexport) const clap_plugin_entry_t clap_entry = {
    .clap_version = CLAP_VERSION_INIT,
    .init         = entry_init,
    .deinit       = entry_deinit,
    .get_factory  = entry_get_factory,
};

// ── DllMain ───────────────────────────────────────────────────────────────────
BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_hInst = hInst;
        DisableThreadLibraryCalls(hInst);
    }
    return TRUE;
}
