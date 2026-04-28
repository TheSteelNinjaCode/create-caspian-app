import { twMerge } from "tailwind-merge";

export type MergeableClassName = string | false | null | undefined;

export function mergeTailwindClasses(
  ...classNames: MergeableClassName[]
): string {
  return twMerge(
    classNames
      .filter((className): className is string => Boolean(className))
      .join(" "),
  );
}