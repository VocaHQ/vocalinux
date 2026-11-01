import React from 'react';
import { render, screen } from '@testing-library/react';
import { DidYouMean, suggestPage } from '../not-found-extras';

const pages = ['/install/', '/install/ubuntu/', '/install/fedora/', '/faq/', '/compare/'];

describe('suggestPage', () => {
  it('suggests the closest page for a typo', () => {
    expect(suggestPage('/install/ubunt', pages)).toBe('/install/ubuntu/');
    expect(suggestPage('/INSTALL/FEDORA', pages)).toBe('/install/fedora/');
    expect(suggestPage('/compar', pages)).toBe('/compare/');
  });

  it('suggests nothing for an unrelated path', () => {
    expect(suggestPage('/wp-admin/setup-config.php', pages)).toBeNull();
  });
});

describe('DidYouMean', () => {
  afterEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('links to the closest page for the current URL', async () => {
    window.history.pushState({}, '', '/install/ubunt');
    render(<DidYouMean />);
    // Jest's next/link ignores trailingSlash, so check the visible path.
    expect(await screen.findByRole('link')).toHaveTextContent('/install/ubuntu/');
  });

  it('does not crash on a malformed percent-escape', () => {
    window.history.pushState({}, '', '/%FF/');
    expect(() => render(<DidYouMean />)).not.toThrow();
  });
});
