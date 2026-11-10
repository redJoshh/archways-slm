/**
 * One serial queue for every model call (plan "model queue and speed
 * recovery", 2026-11-10). llama.rn runs one completion at a time on a
 * context: on the Redmi 10C a query call made while priming was running
 * failed after 118 ms with no timings.
 *
 * - run(job): model calls (session load + completion, token counts). First
 *   in, first out, one at a time.
 * - exclusive(job): priming and re-measuring. Runs after the jobs queued
 *   before it, and only once no activity is active. While an exclusive job
 *   is queued or running, beginActivity() waits, so nothing new starts.
 * - beginActivity(): the app's non-model work that competes for the CPU
 *   (the feed index build and refresh). Resolves to end() once no exclusive
 *   job is queued or running. Exclusive jobs wait only for activities that
 *   already started, so the two never deadlock.
 * - overlap: a job's result says whether any activity was active at any
 *   moment while it ran. Its timings are then not a clean speed sample.
 *   Model jobs never overlap each other: the queue is serial.
 *
 * State changes are applied synchronously when a waiter is released, so no
 * other code can slip in between "allowed" and "started".
 *
 * No async arrow functions: the Hermes 0.12 CLI used for the parity smoke
 * test rejects them (async function expressions are fine).
 */

export interface QueueResult<T> {
  value: T;
  /** True if an activity was active at any moment while the job ran. */
  overlap: boolean;
}

export interface ModelQueue {
  run<T>(job: () => Promise<T>): Promise<QueueResult<T>>;
  exclusive<T>(job: () => Promise<T>): Promise<QueueResult<T>>;
  beginActivity(): Promise<() => void>;
  /** An exclusive job is queued or running. */
  busy(): boolean;
  /** Resolves when no exclusive job is queued or running. */
  whenIdle(): Promise<void>;
  /** Called after every state change; returns an unsubscribe function. */
  onChange(listener: () => void): () => void;
}

interface Waiter {
  ready: () => boolean;
  /** Runs synchronously at release, before any other code. */
  take: () => void;
  resolve: () => void;
}

export function createModelQueue(): ModelQueue {
  let tail: Promise<unknown> = Promise.resolve();
  let activities = 0;
  let exclusivePending = 0;
  let current: { overlap: boolean } | null = null;
  const waiters: Waiter[] = [];
  const listeners: (() => void)[] = [];

  function notify(): void {
    let released = true;
    while (released) {
      released = false;
      for (let i = 0; i < waiters.length; i++) {
        const waiter = waiters[i];
        if (waiter.ready()) {
          waiters.splice(i, 1);
          waiter.take();
          waiter.resolve();
          released = true;
          break;
        }
      }
    }
    for (const listener of listeners.slice()) {
      try {
        listener();
      } catch (error) {
        // A listener never breaks the queue.
      }
    }
  }

  function waitFor(ready: () => boolean, take: () => void): Promise<void> {
    if (ready()) {
      take();
      return Promise.resolve();
    }
    return new Promise<void>((resolve) => {
      waiters.push({ ready: ready, take: take, resolve: resolve });
    });
  }

  function enqueue<T>(job: () => Promise<T>, isExclusive: boolean): Promise<QueueResult<T>> {
    if (isExclusive) exclusivePending++;
    const result = tail.then(async function () {
      const record = { overlap: false };
      if (isExclusive) {
        await waitFor(
          () => activities === 0,
          () => {
            current = record;
          },
        );
      } else {
        record.overlap = activities > 0;
        current = record;
      }
      try {
        const value = await job();
        return { value: value, overlap: record.overlap };
      } finally {
        current = null;
        if (isExclusive) exclusivePending--;
        notify();
      }
    });
    // The next job waits for this one, whether it resolved or rejected.
    tail = result.then(
      () => undefined,
      () => undefined,
    );
    if (isExclusive) notify();
    return result;
  }

  return {
    run: (job) => enqueue(job, false),
    exclusive: (job) => enqueue(job, true),
    beginActivity: async function () {
      await waitFor(
        () => exclusivePending === 0,
        () => {
          activities++;
          if (current) current.overlap = true;
        },
      );
      notify();
      let ended = false;
      return () => {
        if (ended) return;
        ended = true;
        activities--;
        notify();
      };
    },
    busy: () => exclusivePending > 0,
    whenIdle: () =>
      waitFor(
        () => exclusivePending === 0,
        () => undefined,
      ),
    onChange: (listener) => {
      listeners.push(listener);
      return () => {
        const i = listeners.indexOf(listener);
        if (i !== -1) listeners.splice(i, 1);
      };
    },
  };
}
