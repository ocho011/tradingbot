    def publish_sync(self, event: Event) -> bool:
        """
        Publish an event to the bus from synchronous context.

        This method directly adds events to the queue without async/await.
        Use this when calling from synchronous code that needs to publish events.

        Args:
            event: The event to publish

        Returns:
            True if the event was queued, False if dropped due to full queue
        """
        if self._queue.size() >= self._max_queue_size:
            self.logger.warning(
                f"Event queue full ({self._max_queue_size}), dropping event {event.event_type}"
            )
            self._stats["dropped"] += 1
            return False

        # Directly add to queue using heapq (bypassing async lock for sync context)
        import heapq
        heapq.heappush(
            self._queue._queue,
            (-event.priority, self._queue._counter, event.timestamp, event)
        )
        self._queue._counter += 1
        self._stats["published"] += 1
        self.logger.debug(f"Published event {event.event_type} with priority {event.priority} (sync)")
        return True
