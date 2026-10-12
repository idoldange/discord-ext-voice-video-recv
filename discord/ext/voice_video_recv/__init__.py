"""
discord.ext.voice_video_recv
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Camera video receive extension for discord.py voice calls, on top of discord.ext.voice_recv.
"""
from .codecs import CODECS
from .decoder import FrameDecoder
from .depacketizer import FrameAssembler
from .patch import install, is_installed, uninstall
from .receiver import VideoReceiver

__title__ = 'discord.ext.voice_video_recv'
__author__ = 'idoldange'
__license__ = 'MIT'
__version__ = '0.1.0'

__all__ = ['VideoReceiver', 'FrameAssembler', 'FrameDecoder', 'CODECS', 'install', 'uninstall', 'is_installed']
