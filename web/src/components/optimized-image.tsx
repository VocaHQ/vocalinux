"use client";

import React from "react";
import Image from "next/image";

interface OptimizedImageProps {
  src: string;
  alt: string;
  width: number;
  height: number;
  className?: string;
  priority?: boolean;
}

/**
 * Optimized image component that uses WebP format with PNG fallback.
 * Browsers that support WebP will load the smaller WebP file, while older
 * browsers will fallback to PNG format.
 */
export const OptimizedImage: React.FC<OptimizedImageProps> = ({
  src,
  alt,
  width,
  height,
  className = "",
  priority = false,
}) => {
  // Get WebP version of the image
  const webpSrc = src.replace(/\.(png|jpg|jpeg)$/i, '.webp');

  // For Next.js Image component with priority and proper optimization
  // we use the Next.js Image with WebP source
  return (
    <picture className={className}>
      <source srcSet={webpSrc} type="image/webp" />
      <Image
        src={src}
        alt={alt}
        width={width}
        height={height}
        className={className}
        priority={priority}
      />
    </picture>
  );
};

/**
 * Specialized Vocalinux logo component with WebP support
 */
export const VocalinuxLogo: React.FC<{
  className?: string;
  width?: number;
  height?: number;
  priority?: boolean;
}> = ({ className = "", width = 32, height = 32, priority = false }) => {
  return (
    // SVG lockup; next/image is for raster.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/brand/vocalinux-mark-circle.svg"
      alt="Vocalinux"
      width={width}
      height={height}
      className={className}
      decoding="async"
      loading={priority ? "eager" : "lazy"}
    />
  );
};
