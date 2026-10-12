# -*- coding: utf-8 -*-

import re

from setuptools import setup

with open('discord/ext/voice_video_recv/__init__.py') as f:
    version = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', f.read(), re.MULTILINE).group(1)  # type: ignore

if not version:
    raise RuntimeError('version is not set')

with open('README.md', encoding='utf-8') as f:
    readme = f.read()

setup(
    name='discord-ext-voice_video_recv',
    author='idoldange',
    url='https://github.com/idoldange/discord-ext-voice-video-recv',
    version=version,
    packages=['discord.ext.voice_video_recv'],
    license='MIT',
    description='Camera video receive extension for discord.py voice calls (builds on discord-ext-voice_recv)',
    long_description=readme,
    long_description_content_type='text/markdown',
    include_package_data=True,
    python_requires='>=3.10',
    install_requires=[
        'discord.py[voice]>=2.7',
        # the fork of discord-ext-voice-recv: it parses the voice gateway VIDEO op and dispatches `voice_member_video`
        'discord-ext-voice_recv @ git+https://github.com/idoldange/discord-ext-voice-recv.git',
        'davey>=0.1.4',
        'av',
        'Pillow',
        'PyNaCl',
    ],
    zip_safe=False,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Internet',
        'Topic :: Multimedia :: Video',
    ],
)
