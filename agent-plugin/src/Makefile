# Agent UI CLAP Plugin – Makefile
# Builds agent-ui.clap (shared library) using g++ and X11

CXX      := g++
CXXFLAGS := -std=c++17 -O2 -fPIC -Wall -Wextra \
            -I../clap/include \
            -I.

LDFLAGS  := -shared -fPIC
LIBS     := -lX11 -lpthread

SRC      := plugin.cpp
TARGET   := ../build/agent-ui.clap

INSTALL_DIR := $(HOME)/.clap

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(SRC) osc.h ui.h
	@mkdir -p $(dir $(TARGET))
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ $(SRC) $(LIBS)
	@echo "Built: $(TARGET)"

install: $(TARGET)
	@mkdir -p $(INSTALL_DIR)
	cp $(TARGET) $(INSTALL_DIR)/
	@echo "Installed to $(INSTALL_DIR)/agent-ui.clap"
	@echo "Restart Bitwig and rescan plugins to use."

clean:
	rm -f $(TARGET)
