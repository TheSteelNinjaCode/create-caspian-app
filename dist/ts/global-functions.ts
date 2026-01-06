export function createGlobalSingleton<T>(
  name: string,
  SingletonClass: { getInstance(): T } | T,
  target: any = window,
  immediateInit: boolean = true
) {
  Object.defineProperty(target, name, {
    get() {
      if (
        SingletonClass &&
        (typeof SingletonClass === "function" ||
          typeof SingletonClass === "object") &&
        "getInstance" in SingletonClass &&
        typeof SingletonClass.getInstance === "function"
      ) {
        return (SingletonClass as { getInstance(): T }).getInstance();
      } else {
        return SingletonClass as T;
      }
    },
    set(next) {
      console.warn(`[${name}] Cannot override global ${name}; ignoring.`, next);
    },
    configurable: false,
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
