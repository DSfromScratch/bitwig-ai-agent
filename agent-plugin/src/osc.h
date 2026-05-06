#pragma once
// Minimal OSC sender/receiver over UDP – no external dependencies
#include <cstdint>
#include <cstring>
#include <string>
#include <functional>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <thread>
#include <atomic>

// ── helpers ──────────────────────────────────────────────────────────────────
static inline int osc_pad4(int n) { return (n + 3) & ~3; }

static inline void osc_write_string(uint8_t*& p, const char* s) {
    int len = strlen(s) + 1;
    memcpy(p, s, len);
    p += osc_pad4(len);
}

static inline void osc_write_int32(uint8_t*& p, int32_t v) {
    int32_t be = htonl(v);
    memcpy(p, &be, 4);
    p += 4;
}

// ── build a simple OSC packet: /path ,s string_arg ───────────────────────────
static inline std::string osc_build_string_msg(const char* path, const char* value) {
    uint8_t buf[2048] = {};
    uint8_t* p = buf;
    osc_write_string(p, path);
    osc_write_string(p, ",s");
    osc_write_string(p, value);
    return std::string(reinterpret_cast<char*>(buf), p - buf);
}

// ── parse OSC packet – returns (path, string_value) or ("","") ───────────────
static inline std::pair<std::string,std::string> osc_parse(const uint8_t* data, int len) {
    if (len < 4) return {};
    const char* p = reinterpret_cast<const char*>(data);
    // address
    std::string path(p);
    int addr_end = osc_pad4(path.size() + 1);
    if (addr_end >= len) return {};
    // type tag
    const char* tags = p + addr_end;
    std::string tag(tags);
    int tag_end = addr_end + osc_pad4(tag.size() + 1);
    if (tag_end >= len) return {};
    // first string arg
    if (tag == ",s") {
        const char* val = p + tag_end;
        return {path, std::string(val)};
    }
    return {path, {}};
}

// ── OSC sender ────────────────────────────────────────────────────────────────
class OscSender {
public:
    OscSender(const char* host, int port) {
        sock = socket(AF_INET, SOCK_DGRAM, 0);
        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        inet_pton(AF_INET, host, &addr.sin_addr);
    }
    ~OscSender() { if (sock >= 0) close(sock); }

    void send_string(const char* path, const char* value) {
        if (sock < 0) return;
        auto pkt = osc_build_string_msg(path, value);
        sendto(sock, pkt.data(), pkt.size(), 0,
               reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    }

private:
    int sock{-1};
    sockaddr_in addr{};
};

// ── OSC receiver (runs in background thread) ──────────────────────────────────
class OscReceiver {
public:
    using Handler = std::function<void(const std::string& path, const std::string& value)>;

    OscReceiver(int port, Handler handler) : handler_(std::move(handler)) {
        sock = socket(AF_INET, SOCK_DGRAM, 0);
        if (sock < 0) return;
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        bind(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));

        // timeout so thread can stop
        timeval tv{0, 100000}; // 100 ms
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        running = true;
        thread_ = std::thread([this]{ loop(); });
    }

    ~OscReceiver() {
        running = false;
        if (thread_.joinable()) thread_.join();
        if (sock >= 0) close(sock);
    }

private:
    void loop() {
        uint8_t buf[4096];
        while (running) {
            int n = recv(sock, buf, sizeof(buf), 0);
            if (n > 0) {
                auto [path, val] = osc_parse(buf, n);
                if (!path.empty()) handler_(path, val);
            }
        }
    }

    int sock{-1};
    std::atomic<bool> running{false};
    std::thread thread_;
    Handler handler_;
};
