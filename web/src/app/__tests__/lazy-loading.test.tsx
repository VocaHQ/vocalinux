import React from 'react';
import { render, screen } from '@testing-library/react';
import { OptimizedImage, VocalinuxLogo } from '../../components/optimized-image';

// Mock Next.js Image component to capture loading behavior
const mockImage = jest.fn();
jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => {
    mockImage(props);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { priority, loading, ...imgProps } = props;
    // eslint-disable-next-line @next/next/no-img-element
    return <img {...imgProps} alt={props.alt} data-priority={priority} data-loading={loading} />;
  },
}));

describe('Lazy Loading Behavior', () => {
  beforeEach(() => {
    mockImage.mockClear();
  });

  describe('OptimizedImage Component', () => {
    const defaultProps = {
      src: '/test.png',
      alt: 'Test',
      width: 100,
      height: 100,
    };

    it('lazy loads images by default (no priority prop)', () => {
      render(<OptimizedImage {...defaultProps} />);
      
      // Check that the image is rendered
      const img = screen.getByAltText('Test');
      expect(img).toBeInTheDocument();
      
      // By default, Next.js Image uses lazy loading when priority is not set
      expect(mockImage).toHaveBeenCalledWith(
        expect.objectContaining({
          priority: false,
        })
      );
    });

    it('eager loads images when priority is true', () => {
      render(<OptimizedImage {...defaultProps} priority />);
      
      expect(mockImage).toHaveBeenCalledWith(
        expect.objectContaining({
          priority: true,
        })
      );
    });

    it('passes loading behavior to Next.js Image', () => {
      render(<OptimizedImage {...defaultProps} priority={false} />);
      
      const call = mockImage.mock.calls[0][0];
      expect(call).toHaveProperty('priority');
    });
  });

  describe('VocalinuxLogo Component', () => {
    it('lazy loads the circular mark by default', () => {
      render(<VocalinuxLogo />);
      const img = screen.getByAltText('Vocalinux');
      expect(img).toHaveAttribute('src', '/brand/vocalinux-mark-circle.svg');
      expect(img).toHaveAttribute('loading', 'lazy');
    });

    it('eager loads the mark when priority is set', () => {
      render(<VocalinuxLogo priority />);
      const img = screen.getByAltText('Vocalinux');
      expect(img).toHaveAttribute('loading', 'eager');
    });
  });

  describe('Performance Best Practices', () => {
    it('maintains aspect ratio with explicit width and height', () => {
      render(<OptimizedImage src="/test.png" alt="Test" width={200} height={150} />);
      
      const img = screen.getByAltText('Test');
      expect(img).toHaveAttribute('width', '200');
      expect(img).toHaveAttribute('height', '150');
    });

    it('prevents layout shift with explicit dimensions', () => {
      render(<VocalinuxLogo width={64} height={64} />);
      const img = screen.getByAltText('Vocalinux');
      expect(img).toHaveAttribute('width', '64');
      expect(img).toHaveAttribute('height', '64');
    });
  });

  describe('WebP Lazy Loading Integration', () => {
    it('provides WebP source even for lazy-loaded images', () => {
      const { container } = render(
        <OptimizedImage src="/hero.png" alt="Hero" width={800} height={400} priority={false} />
      );
      
      // Even lazy-loaded images should have WebP support
      const source = container.querySelector('source');
      expect(source).toHaveAttribute('srcset', '/hero.webp');
      expect(source).toHaveAttribute('type', 'image/webp');
    });

    it('ships the circular mark as an SVG', () => {
      render(<VocalinuxLogo width={32} height={32} />);
      const img = screen.getByAltText('Vocalinux');
      expect(img).toHaveAttribute('src', '/brand/vocalinux-mark-circle.svg');
    });
  });
});
