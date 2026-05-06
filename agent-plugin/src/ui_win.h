#pragma once
// Win32 UI for the Agent CLAP plugin
// Provides: text input (EDIT control), send button, multiline response area
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <commctrl.h>
#include <string>
#include <functional>
#pragma comment(lib, "comctl32.lib")

#define AGENT_UI_BTN_SEND   0x101
#define AGENT_UI_EDT_PROMPT 0x102
#define AGENT_UI_TXT_RESP   0x103

static LRESULT CALLBACK AgentUIWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);

struct AgentUI {
    using SendCallback = std::function<void(const std::string& prompt)>;

    static constexpr int W = 420;
    static constexpr int H = 300;

    HWND win{};
    HWND edit_prompt{};
    HWND btn_send{};
    HWND txt_response{};
    HFONT font{};

    SendCallback on_send;

    static const wchar_t* CLASS_NAME() { return L"AgentUIPlugin"; }

    bool register_class(HINSTANCE hInst) {
        WNDCLASSEXW wc{};
        wc.cbSize        = sizeof(wc);
        wc.lpfnWndProc   = AgentUIWndProc;
        wc.hInstance     = hInst;
        wc.hbrBackground = CreateSolidBrush(RGB(30, 30, 46));  // catppuccin base
        wc.lpszClassName = CLASS_NAME();
        wc.cbWndExtra    = sizeof(AgentUI*);
        RegisterClassExW(&wc);   // ignore duplicate-register error
        return true;
    }

    bool create(HWND parent, HINSTANCE hInst) {
        register_class(hInst);

        RECT rc{};
        GetClientRect(parent, &rc);
        int pw = rc.right  > 0 ? rc.right  : W;
        int ph = rc.bottom > 0 ? rc.bottom : H;

        win = CreateWindowExW(0, CLASS_NAME(), L"Agent UI",
                              WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN,
                              0, 0, pw, ph, parent, nullptr, hInst, this);
        if (!win) return false;

        font = CreateFontW(-13, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                           DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                           CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Consolas");

        // Prompt edit
        edit_prompt = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
            WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
            8, 28, pw - 100, 24, win,
            reinterpret_cast<HMENU>(AGENT_UI_EDT_PROMPT), hInst, nullptr);

        // Send button
        btn_send = CreateWindowExW(0, L"BUTTON", L"Send",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            pw - 88, 28, 80, 24, win,
            reinterpret_cast<HMENU>(AGENT_UI_BTN_SEND), hInst, nullptr);

        // Response static/edit (read-only multiline)
        txt_response = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
            WS_CHILD | WS_VISIBLE | WS_VSCROLL |
            ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL,
            8, 72, pw - 16, ph - 80, win,
            reinterpret_cast<HMENU>(AGENT_UI_TXT_RESP), hInst, nullptr);

        // Apply font to all children
        for (HWND h : {edit_prompt, btn_send, txt_response})
            SendMessage(h, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);

        UpdateWindow(win);
        return true;
    }

    void destroy() {
        if (font) { DeleteObject(font); font = nullptr; }
        if (win)  { DestroyWindow(win); win = nullptr; }
    }

    void set_size(int w, int h) {
        if (!win) return;
        SetWindowPos(win, nullptr, 0, 0, w, h, SWP_NOMOVE | SWP_NOZORDER);
        // re-layout children
        if (edit_prompt)  SetWindowPos(edit_prompt,  nullptr, 8, 28, w-100, 24, SWP_NOZORDER);
        if (btn_send)     SetWindowPos(btn_send,     nullptr, w-88, 28, 80, 24, SWP_NOZORDER);
        if (txt_response) SetWindowPos(txt_response, nullptr, 8, 72, w-16, h-80, SWP_NOZORDER);
    }

    void set_response(const std::wstring& text) {
        if (txt_response) {
            SetWindowTextW(txt_response, text.c_str());
            // scroll to bottom
            SendMessage(txt_response, EM_SETSEL, (WPARAM)-1, (LPARAM)-1);
            SendMessage(txt_response, EM_SCROLLCARET, 0, 0);
        }
    }

    void set_response(const std::string& text) {
        int n = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
        std::wstring ws(n, 0);
        MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, ws.data(), n);
        set_response(ws);
    }

    void clear_prompt() {
        if (edit_prompt) SetWindowTextW(edit_prompt, L"");
    }

    std::string get_prompt() {
        if (!edit_prompt) return {};
        int len = GetWindowTextLengthW(edit_prompt);
        if (len == 0) return {};
        std::wstring ws(len + 1, 0);
        GetWindowTextW(edit_prompt, ws.data(), len + 1);
        ws.resize(len);
        int n = WideCharToMultiByte(CP_UTF8, 0, ws.c_str(), -1, nullptr, 0, nullptr, nullptr);
        std::string s(n, 0);
        WideCharToMultiByte(CP_UTF8, 0, ws.c_str(), -1, s.data(), n, nullptr, nullptr);
        s.resize(strlen(s.c_str()));
        return s;
    }

    void fire_send() {
        auto p = get_prompt();
        if (!p.empty() && on_send) on_send(p);
    }
};

// WndProc defined out-of-line so it can reference AgentUI
static LRESULT CALLBACK AgentUIWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    AgentUI* ui = reinterpret_cast<AgentUI*>(GetWindowLongPtrW(hwnd, 0));

    switch (msg) {
    case WM_CREATE: {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lp);
        ui = reinterpret_cast<AgentUI*>(cs->lpCreateParams);
        SetWindowLongPtrW(hwnd, 0, reinterpret_cast<LONG_PTR>(ui));
        return 0;
    }
    case WM_CTLCOLOREDIT:
    case WM_CTLCOLORSTATIC: {
        HDC hdc = reinterpret_cast<HDC>(wp);
        SetTextColor(hdc, RGB(205, 214, 244));   // lavender text
        SetBkColor(hdc,   RGB(49,  50,  68));    // surface0
        static HBRUSH bg = CreateSolidBrush(RGB(49, 50, 68));
        return reinterpret_cast<LRESULT>(bg);
    }
    case WM_ERASEBKGND: {
        HDC hdc = reinterpret_cast<HDC>(wp);
        RECT rc; GetClientRect(hwnd, &rc);
        HBRUSH br = CreateSolidBrush(RGB(30, 30, 46));
        FillRect(hdc, &rc, br);
        DeleteObject(br);
        return 1;
    }
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hwnd, &ps);
        // Draw labels
        SetBkColor(hdc, RGB(30, 30, 46));
        SetTextColor(hdc, RGB(137, 180, 250));  // blue
        HFONT font = ui ? ui->font : nullptr;
        if (font) SelectObject(hdc, font);
        TextOutA(hdc, 8, 8,  "Prompt:",   7);
        TextOutA(hdc, 8, 56, "Response:", 9);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_COMMAND: {
        if (!ui) break;
        WORD id  = LOWORD(wp);
        WORD evt = HIWORD(wp);
        if (id == AGENT_UI_BTN_SEND && evt == BN_CLICKED) {
            ui->fire_send();
        }
        if (id == AGENT_UI_EDT_PROMPT && evt == EN_CHANGE) {
            // Enter key in edit → send
            // (handled via WM_KEYDOWN in edit subclass – keep simple for now)
        }
        break;
    }
    case WM_KEYDOWN:
        if (wp == VK_RETURN && ui) { ui->fire_send(); return 0; }
        break;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}
