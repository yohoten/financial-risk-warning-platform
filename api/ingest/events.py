"""进程内事件总线（SSE 事件流后端）。

单机（桌面/演示）形态用进程内 asyncio 总线；生产多 worker 下经 Redis pub/sub
扇出（接口一致，P4 替换实现）。publish 线程安全：同步 handler 在 worker 线程
里通过 ``call_soon_threadsafe`` 派发给事件循环内的订阅者；同时保留最近事件
环形缓冲，供迟到的订阅者回放。
"""

from __future__ import annotations

import asyncio
import collections
import threading
import time


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recent: collections.deque = collections.deque(maxlen=50)
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self) -> asyncio.Queue:
        """订阅；在事件循环内调用，自动捕获 loop 并回放最近事件。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            self._loop = loop
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subs.add(q)
            recent = list(self._recent)
        for e in recent:
            try:
                q.put_nowait(e)
            except asyncio.QueueFull:
                pass
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, event_type: str, data: dict) -> None:
        """发布事件；线程安全，无活跃 loop 时仅写入最近事件缓冲。"""
        event = {"type": event_type, "data": data, "ts": time.time()}
        with self._lock:
            self._recent.append(event)
            loop = self._loop
        if loop is None or loop.is_closed():
            return

        def _dispatch() -> None:
            with self._lock:
                subs = list(self._subs)
            for q in subs:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        try:
            loop.call_soon_threadsafe(_dispatch)
        except RuntimeError:  # pragma: no cover —— loop 已关闭
            pass


bus = EventBus()
