export interface HostLogoPreset {
  key: string;
  label: string;
  src: string;
  darkSrc?: string;
  isWide?: boolean;
}

export const HOST_LOGO_PRESETS: HostLogoPreset[] = [
  {
    key: "istoreos",
    label: "iStoreOS",
    src: "/vendor-logos/istoreos.svg",
  },
  {
    key: "zspace",
    label: "极空间 (ZSpace)",
    src: "/vendor-logos/zspace.png",
  },
  {
    key: "oracle",
    label: "Oracle Cloud (甲骨文)",
    src: "/vendor-logos/oracle.svg",
  },
  {
    key: "cloudcone",
    label: "CloudCone",
    src: "/vendor-logos/cloudcone.png",
  },
  {
    key: "zgocloud",
    label: "ZGO Cloud",
    src: "/vendor-logos/zgocloud.png",
  },
  {
    key: "lightlayer",
    label: "Lightlayer",
    src: "/vendor-logos/lightlayer.svg",
    darkSrc: "/vendor-logos/lightlayer-dark.svg",
  },
];

const PRESET_MAP = new Map<string, HostLogoPreset>(
  HOST_LOGO_PRESETS.map((item) => [item.key, item]),
);

export interface ResolvedHostLogo {
  key: string;
  src: string;
  darkSrc: string;
  isWide: boolean;
}

export function resolveHostLogo(
  logo: string | null | undefined,
): ResolvedHostLogo | null {
  const raw = (logo || "").trim();
  if (!raw) return null;

  const preset = PRESET_MAP.get(raw.toLowerCase());
  if (preset) {
    return {
      key: preset.key,
      src: preset.src,
      darkSrc: preset.darkSrc || preset.src,
      isWide: Boolean(preset.isWide),
    };
  }

  const normalizedUrl =
    /^https?:\/\//.test(raw) || raw.startsWith("/")
      ? raw
      : `/api/static/icons/${raw}`;

  return {
    key: "custom",
    src: normalizedUrl,
    darkSrc: normalizedUrl,
    isWide: false,
  };
}
