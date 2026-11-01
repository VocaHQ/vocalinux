import { suggestPage } from '../not-found-extras';

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
