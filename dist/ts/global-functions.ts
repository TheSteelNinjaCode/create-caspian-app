export type GlobalSingletonOptions = {
  cache?: boolean;
  configurable?: boolean;
  resetOnNull?: boolean;
};

export function createGlobalSingleton<T>(
  name: string,
  SingletonClass: { getInstance(): T } | T,
  target: any = typeof window !== "undefined" ? window : globalThis,
  immediateInit: boolean = true,
  options: GlobalSingletonOptions = {},
): void {
  const {
    cache = false,
    configurable = false,
    resetOnNull = false,
  } = options;
  let hasCachedInstance = false;
  let cachedInstance: T;

  const resolve = (): T => {
    if (cache && hasCachedInstance) {
      return cachedInstance;
    }

    const candidate = SingletonClass as
      | ({ getInstance?: () => T } & object)
      | ({ getInstance?: () => T } & Function)
      | T;
    const resolved =
      candidate !== null &&
      (typeof candidate === "function" || typeof candidate === "object") &&
      "getInstance" in candidate &&
      typeof candidate.getInstance === "function"
        ? candidate.getInstance()
        : (SingletonClass as T);

    if (cache) {
      cachedInstance = resolved;
      hasCachedInstance = true;
    }

    return resolved;
  };

  Object.defineProperty(target, name, {
    get() {
      return resolve();
    },
    set(next) {
      if (resetOnNull && next === null) {
        hasCachedInstance = false;
        return;
      }

      console.warn(`[${name}] Cannot override global ${name}; ignoring.`, next);
    },
    configurable,
    enumerable: true,
  });

  if (immediateInit) {
    try {
      target[name];
    } catch (error) {
      console.error(`Failed to initialize ${name}:`, error);
    }
  }
}
