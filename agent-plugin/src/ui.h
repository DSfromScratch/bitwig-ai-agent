#pragma once
// Minimal X11 UI layer for the Agent CLAP plugin
// Provides: text input field, send button, response text area
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <string>
#include <vector>
#include <functional>
#include <algorithm>
#include <sstream>

struct AgentUI {
    using SendCallback = std::function<void(const std::string& prompt)>;

    // ── colours ──────────────────────────────────────────────────────────────
    static constexpr int W = 420;
    static constexpr int H = 300;

    Display* dpy{};
    Window   win{};
    GC       gc{};
    XFontStruct* font{};

    std::string prompt_buf;
    std::string response_text;
    bool focused_on_input{true};
    SendCallback on_send;

    // ── init ─────────────────────────────────────────────────────────────────
    bool create(Display* display, Window parent, int x, int y, int w, int h) {
        dpy = display;
        int width  = w  > 0 ? w  : W;
        int height = h > 0 ? h : H;

        XSetWindowAttributes attrs{};
        attrs.background_pixel = 0x1E1E2E;   // dark bg
        attrs.border_pixel      = 0x89B4FA;
        attrs.event_mask = ExposureMask | KeyPressMask | ButtonPressMask
                         | FocusChangeMask | StructureNotifyMask;
        win = XCreateWindow(dpy, parent, x, y, width, height, 0,
                            CopyFromParent, InputOutput, CopyFromParent,
                            CWBackPixel | CWBorderPixel | CWEventMask, &attrs);
        if (!win) return false;

        gc = XCreateGC(dpy, win, 0, nullptr);

        // Try to load a decent font; fall back to fixed
        font = XLoadQueryFont(dpy, "-*-dejavu sans mono-medium-r-*-*-13-*-*-*-*-*-*-*");
        if (!font) font = XLoadQueryFont(dpy, "fixed");
        if (font) XSetFont(dpy, gc, font->fid);

        XMapWindow(dpy, win);
        XFlush(dpy);
        return true;
    }

    void destroy() {
        if (font) { XFreeFont(dpy, font); font = nullptr; }
        if (gc)   { XFreeGC(dpy, gc);    gc = nullptr; }
        if (win)  { XDestroyWindow(dpy, win); win = 0; }
    }

    void set_size(int w, int h) {
        if (win) XResizeWindow(dpy, win, w, h);
    }

    void get_size(int& w, int& h) { w = W; h = H; }

    // ── drawing ──────────────────────────────────────────────────────────────
    void draw() {
        if (!win) return;
        XWindowAttributes wa;
        XGetWindowAttributes(dpy, win, &wa);
        int ow = wa.width, oh = wa.height;

        // ── background
        XSetForeground(dpy, gc, 0x1E1E2E);
        XFillRectangle(dpy, win, gc, 0, 0, ow, oh);

        int fm_ascent = font ? font->ascent : 10;
        int fm_height = font ? (font->ascent + font->descent + 2) : 14;

        // ── label "Prompt:"
        XSetForeground(dpy, gc, 0x89B4FA);
        draw_text(8, 8 + fm_ascent, "Prompt:");

        // ── input box
        int box_x = 8, box_y = 8 + fm_height + 4;
        int box_w = ow - 100, box_h = fm_height + 6;
        XSetForeground(dpy, gc, 0x313244);
        XFillRectangle(dpy, win, gc, box_x, box_y, box_w, box_h);
        XSetForeground(dpy, gc, focused_on_input ? 0x89B4FA : 0x585B70);
        XDrawRectangle(dpy, win, gc, box_x, box_y, box_w, box_h);

        // prompt text (clipped)
        XSetForeground(dpy, gc, 0xCDD6F4);
        std::string visible = prompt_buf;
        // simple clip: measure char by char
        if (font) {
            while (!visible.empty()) {
                int tw = XTextWidth(font, visible.c_str(), visible.size());
                if (tw <= box_w - 10) break;
                visible.erase(0, 1);
            }
        }
        draw_text(box_x + 5, box_y + 3 + fm_ascent, visible.c_str());

        // cursor
        if (focused_on_input) {
            int cx = box_x + 5 + (font && !visible.empty()
                ? XTextWidth(font, visible.c_str(), visible.size()) : 0);
            XSetForeground(dpy, gc, 0x89B4FA);
            XDrawLine(dpy, win, gc, cx, box_y + 3, cx, box_y + box_h - 3);
        }

        // ── Send button
        int btn_x = box_x + box_w + 8, btn_y = box_y;
        int btn_w = ow - btn_x - 8, btn_h = box_h;
        XSetForeground(dpy, gc, 0x89B4FA);
        XFillRectangle(dpy, win, gc, btn_x, btn_y, btn_w, btn_h);
        XSetForeground(dpy, gc, 0x1E1E2E);
        draw_text_centered(btn_x, btn_y, btn_w, btn_h, "Send");

        // ── separator
        int sep_y = box_y + box_h + 8;
        XSetForeground(dpy, gc, 0x45475A);
        XDrawLine(dpy, win, gc, 8, sep_y, ow - 8, sep_y);

        // ── label "Response:"
        XSetForeground(dpy, gc, 0x89B4FA);
        draw_text(8, sep_y + 6 + fm_ascent, "Response:");

        // ── response text (word-wrapped)
        int resp_y = sep_y + 6 + fm_height + 4;
        int resp_x = 8;
        int resp_w = ow - 16;
        XSetForeground(dpy, gc, 0xA6E3A1);
        auto lines = wrap_text(response_text, resp_w);
        int max_lines = (oh - resp_y - 4) / fm_height;
        // show last lines if too many
        int start = lines.size() > (size_t)max_lines
                    ? (int)lines.size() - max_lines : 0;
        for (int i = start; i < (int)lines.size(); ++i) {
            draw_text(resp_x, resp_y + (i - start) * fm_height + fm_ascent,
                      lines[i].c_str());
        }

        XFlush(dpy);
    }

    // ── event processing (call from main/timer thread) ────────────────────────
    // Returns true if we consumed the event
    bool process_event(XEvent& ev) {
        if (ev.xany.window != win) return false;

        switch (ev.type) {
        case Expose:
            draw();
            return true;

        case KeyPress: {
            char buf[16]{};
            KeySym ks;
            XLookupString(&ev.xkey, buf, sizeof(buf) - 1, &ks, nullptr);
            if (ks == XK_BackSpace) {
                if (!prompt_buf.empty()) prompt_buf.pop_back();
            } else if (ks == XK_Return || ks == XK_KP_Enter) {
                if (!prompt_buf.empty() && on_send) {
                    on_send(prompt_buf);
                }
            } else if (buf[0] >= 0x20 && buf[0] < 0x7F) {
                if (prompt_buf.size() < 500)
                    prompt_buf += buf[0];
            }
            draw();
            return true;
        }

        case ButtonPress: {
            // Check if click on Send button
            XWindowAttributes wa;
            XGetWindowAttributes(dpy, win, &wa);
            int ow = wa.width;
            int fm_height = font ? (font->ascent + font->descent + 2) : 14;
            int box_y = 8 + fm_height + 4;
            int box_h = fm_height + 6;
            int box_w = ow - 100;
            int btn_x = 8 + box_w + 8;
            int btn_y = box_y;
            int btn_w = ow - btn_x - 8;
            int bx = ev.xbutton.x, by = ev.xbutton.y;
            if (bx >= btn_x && bx < btn_x + btn_w &&
                by >= btn_y && by < btn_y + box_h) {
                if (!prompt_buf.empty() && on_send) {
                    on_send(prompt_buf);
                }
            } else {
                focused_on_input = (bx >= 8 && bx < 8 + box_w &&
                                    by >= box_y && by < box_y + box_h);
                XSetInputFocus(dpy, win, RevertToParent, CurrentTime);
            }
            draw();
            return true;
        }

        case ConfigureNotify:
            draw();
            return true;

        default:
            return false;
        }
    }

    void set_response(const std::string& text) {
        response_text = text;
        draw();
    }

    void clear_prompt() {
        prompt_buf.clear();
        draw();
    }

private:
    void draw_text(int x, int y, const char* text) {
        if (!text || !*text) return;
        XDrawString(dpy, win, gc, x, y, text, strlen(text));
    }

    void draw_text_centered(int bx, int by, int bw, int bh, const char* text) {
        int tw = font ? XTextWidth(font, text, strlen(text)) : (int)strlen(text) * 7;
        int fm_ascent = font ? font->ascent : 10;
        int fm_height = font ? (font->ascent + font->descent) : 13;
        draw_text(bx + (bw - tw) / 2, by + (bh - fm_height) / 2 + fm_ascent, text);
    }

    std::vector<std::string> wrap_text(const std::string& text, int max_w) {
        std::vector<std::string> result;
        if (text.empty()) return result;
        std::istringstream iss(text);
        std::string word, line;
        while (iss >> word) {
            std::string test = line.empty() ? word : line + " " + word;
            int tw = font ? XTextWidth(font, test.c_str(), test.size())
                          : (int)test.size() * 7;
            if (tw > max_w && !line.empty()) {
                result.push_back(line);
                line = word;
            } else {
                line = test;
            }
        }
        if (!line.empty()) result.push_back(line);
        return result;
    }
};
