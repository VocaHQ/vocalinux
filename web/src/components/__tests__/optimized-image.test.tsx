import React from 'react';
import { render, screen } from '@testing-library/react';
import { OptimizedImage, VocalinuxLogo } from '../optimized-image';

// Mock Next.js Image component
jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { priority, ...imgProps } = props;
    // eslint-disable-next-line @next/next/no-img-element
    return <img {...imgProps} alt={props.alt} />;
  },
}));

describe('OptimizedImage', () => {
  const defaultProps = {
    src: '/test-image.png',
    alt: 'Test Image',
    width: 100,
    height: 100,
  };

  it('renders without crashing', () => {
    render(<OptimizedImage {...defaultProps} />);
    const img = screen.getByAltText('Test Image');
    expect(img).toBeInTheDocument();
  });

  it('renders a picture element with WebP source', () => {
    const { container } = render(<OptimizedImage {...defaultProps} />);
    const picture = container.querySelector('picture');
    expect(picture).toBeInTheDocument();

    const source = container.querySelector('source');
    expect(source).toBeInTheDocument();
    expect(source).toHaveAttribute('srcset', '/test-image.webp');
    expect(source).toHaveAttribute('type', 'image/webp');
  });

  it('provides PNG fallback for browsers without WebP support', () => {
    render(<OptimizedImage {...defaultProps} />);
    const img = screen.getByAltText('Test Image');
    expect(img).toHaveAttribute('src', '/test-image.png');
  });

  it('converts jpg to webp in source srcset', () => {
    const { container } = render(
      <OptimizedImage {...defaultProps} src="/image.jpg" />
    );
    const source = container.querySelector('source');
    expect(source).toHaveAttribute('srcset', '/image.webp');
  });

  it('converts jpeg to webp in source srcset', () => {
    const { container } = render(
      <OptimizedImage {...defaultProps} src="/image.jpeg" />
    );
    const source = container.querySelector('source');
    expect(source).toHaveAttribute('srcset', '/image.webp');
  });

  it('handles case-insensitive extensions', () => {
    const { container } = render(
      <OptimizedImage {...defaultProps} src="/image.PNG" />
    );
    const source = container.querySelector('source');
    expect(source).toHaveAttribute('srcset', '/image.webp');
  });

  it('applies custom className to picture element', () => {
    const { container } = render(
      <OptimizedImage {...defaultProps} className="custom-class" />
    );
    const picture = container.querySelector('picture');
    expect(picture).toHaveClass('custom-class');
  });

  it('passes priority prop to Image component', () => {
    render(<OptimizedImage {...defaultProps} priority />);
    const img = screen.getByAltText('Test Image');
    // Priority images should not have loading="lazy"
    expect(img).not.toHaveAttribute('loading', 'lazy');
  });

  it('sets correct dimensions on the image', () => {
    render(<OptimizedImage {...defaultProps} width={200} height={150} />);
    const img = screen.getByAltText('Test Image');
    expect(img).toHaveAttribute('width', '200');
    expect(img).toHaveAttribute('height', '150');
  });
});

describe('VocalinuxLogo', () => {
  it('renders without crashing', () => {
    render(<VocalinuxLogo />);
    const img = screen.getByAltText('Vocalinux');
    expect(img).toBeInTheDocument();
  });

  it('uses the circular mark', () => {
    render(<VocalinuxLogo />);
    const img = screen.getByAltText('Vocalinux');
    expect(img).toHaveAttribute('src', '/brand/vocalinux-mark-circle.svg');
  });

  it('uses default dimensions when not specified', () => {
    render(<VocalinuxLogo />);
    const img = screen.getByAltText('Vocalinux');
    expect(img).toHaveAttribute('width', '32');
    expect(img).toHaveAttribute('height', '32');
  });

  it('accepts custom dimensions', () => {
    render(<VocalinuxLogo width={64} height={64} />);
    const img = screen.getByAltText('Vocalinux');
    expect(img).toHaveAttribute('width', '64');
    expect(img).toHaveAttribute('height', '64');
  });

  it('applies custom className', () => {
    render(<VocalinuxLogo className="logo-class" />);
    const img = screen.getByAltText('Vocalinux');
    expect(img).toHaveClass('logo-class');
  });

  it('passes priority prop for eager loading', () => {
    render(<VocalinuxLogo priority />);
    const img = screen.getByAltText('Vocalinux');
    expect(img).toHaveAttribute('loading', 'eager');
  });
});
