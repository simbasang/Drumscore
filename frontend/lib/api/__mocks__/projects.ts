const actual = jest.requireActual<typeof import("../projects")>("../projects");

export const NotFoundError = actual.NotFoundError;
export const DuplicateProjectError = actual.DuplicateProjectError;
export const ScoreConflictError = actual.ScoreConflictError;
export const audioUrl = jest.fn(actual.audioUrl);
export const createProject = jest.fn();
export const listProjects = jest.fn();
export const getProject = jest.fn();
export const deleteProject = jest.fn();
export const retryProject = jest.fn();
export const getAnalysis = jest.fn();
export const getSavedScore = jest.fn();
export const saveScore = jest.fn();
