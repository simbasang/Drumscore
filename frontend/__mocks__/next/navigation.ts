export const mockPush = jest.fn();

export const useRouter = jest.fn(() => ({
  push: mockPush,
  replace: jest.fn(),
  back: jest.fn(),
  forward: jest.fn(),
  refresh: jest.fn(),
  prefetch: jest.fn(),
}));
