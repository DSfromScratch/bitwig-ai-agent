#pragma once
// Minimal OSC sender/receiver for Windows (Winsock2) – no external dependencies
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <cstdint>
#include <cstring>
#include <string>
#include <functional>
#include <thread>
#include <atomic>
#pragma comment(lib, "Ws2_32.lib")

// ── helpers ──────────────────────────────────────────────────────────────────
static inline int osc_pad4(int n) { return (n + 3) & ~3; }

static inline void osc_write_string(uint8_t*& p, const char* s) {
    int len = (int)strlen(s) + 1;
    memcpy(p, s, len);
    p += osc_pad4(len);
}

static inline std::string osc_build_string_msg(const char* path, const char* value) {
    uint8_t buf[2048] = {};
    uint8_t* p = buf;
    osc_write_string(p, path);
    osc_write_string(p, ",s");
    osc_write_string(p, value);
    return std::string(reinterpret_cast<char*>(buf), p - buf);
}

static inline std::pair<std::string,std::string> osc_parse(const uint8_t* data, int len) {
    if (len < 4) return {};
    const char* p = reinterpret_cast<const char*>(data);
    std::string path(p);
    int addr_end = osc_pad4((int)path.size() + 1);
    if (addr_end >= len) return {};
    const char* tags = p + addr_end;
    std::string tag(tags);
    int tag_end = addr_end + osc_pad4((int)tag.size() + 1);
    if (tag_end >= len) return {};
    if (tag == ",s") {
        const char* val = p + tag_end;
        return {path, std::string(val)};
    }
    return {path, {}};
}

// ── WSA init guard ────────────────────────────────────────────────────────────
struct WsaInit {
    WsaInit()  { WSADATA d{}; WSAStartup(MAKEWORD(2,2), &d); }
    ~WsaInit() { WSACleanup(); }
};

// ── OSC sender ────────────────────────────────────────────────────────────────
class OscSender {
public:
    OscSender(const char* host, int port) {
        static WsaInit wsa;
        sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        addr = {};
        addr.sin_family = AF_INET;
        addr.sin_port   = htons((u_short)port);
        inet_pton(AF_INET, host, &addr.sin_addr);
    }
    ~OscSender() { if (sock != INVALID_SOCKET) closesocket(sock); }

    void send_string(const char* path, const char* value) {
        if (sock == INVALID_SOCKET) return;
        auto pkt = osc_build_string_msg(path, value);
        sendto(sock, pkt.data(), (int)pkt.size(), 0,
               reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    }

private:
    SOCKET      sock{INVALID_SOCKET};
    sockaddr_in addr{};
};

// ── OSC receiver ─────────────────────────────────────────────────────────────
class OscReceiver {
public:
    using Handler = std::function<void(const std::string& path, const std::string& value)>;

    OscReceiver(int port, Handler handler) : handler_(std::move(handler)) {
        static WsaInit wsa;
        sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (sock == INVALID_SOCKET) return;
        sockaddr_in addr{};
        addr.sin_family      = AF_INET;
        addr.sin_port        = htons((u_short)port);
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        bind(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
        DWORD timeout = 100; // 100 ms
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO,
                   reinterpret_cast<char*>(&timeout), sizeof(timeout));
        running = true;
        thread_ = std::thread([this]{ loop(); });
    }

    ~OscReceiver() {
        running = false;
        if (thread_.joinable()) thread_.join();
        if (sock != INVALID_SOCKET) closesocket(sock);
    }

private:
    void loop() {
        uint8_t buf[4096];
        while (running) {
            int n = recv(sock, reinterpret_cast<char*>(buf), sizeof(buf), 0);
            if (n > 0) {
                auto [path, val] = osc_parse(buf, n);
                if (!path.empty()) handler_(path, val);
            }
        }
    }

    SOCKET sock{INVALID_SOCKET};
    std::atomic<bool> running{false};
    std::thread thread_;
    Handler handler_;
};
