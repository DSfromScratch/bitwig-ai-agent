"""Slave-Agents für den Bitwig Master-Graph."""
from src.agent.slaves.instrument_slave import run_instrument_slave
from src.agent.slaves.note_slave import run_note_slave
from src.agent.slaves.assemble import assemble_node

__all__ = ["run_instrument_slave", "run_note_slave", "assemble_node"]
