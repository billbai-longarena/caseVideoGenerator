const clampValue = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const charUnits = (char: string) => {
  if (/\s/u.test(char)) return 0.34;
  if (/[\u2e80-\u9fff\uf900-\ufaff]/u.test(char)) return 1;
  if (/[A-Z0-9]/u.test(char)) return 0.66;
  if (/[a-z]/u.test(char)) return 0.56;
  return 0.48;
};

export const estimatedTextUnits = (text: string) =>
  Array.from(text).reduce((sum, char) => sum + charUnits(char), 0);

export const fitSingleLineFontSize = ({
  text,
  maxWidth,
  preferred,
  min,
  safety = 0.92,
}: {
  text: string;
  maxWidth: number;
  preferred: number;
  min: number;
  safety?: number;
}) => {
  const longestLine = Math.max(
    1,
    ...text.split("\n").map((line) => estimatedTextUnits(line.trim())),
  );
  return clampValue((maxWidth * safety) / longestLine, min, preferred);
};

export const fitTextBlockFontSize = ({
  text,
  maxWidth,
  maxLines,
  preferred,
  min,
  safety = 0.9,
}: {
  text: string;
  maxWidth: number;
  maxLines: number;
  preferred: number;
  min: number;
  safety?: number;
}) => {
  const explicitLines = text.split("\n");
  const unitsPerLine = explicitLines.length > 1
    ? Math.max(...explicitLines.map((line) => estimatedTextUnits(line.trim())), 1)
    : Math.max(1, Math.ceil(estimatedTextUnits(text.trim()) / Math.max(1, maxLines)));
  return clampValue((maxWidth * safety) / unitsPerLine, min, preferred);
};
