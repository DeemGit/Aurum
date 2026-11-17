import { api } from "@/api/client";
import type { TodoInput, TodoItem } from "@/types";

export function fetchTodos(includeDeleted = false) {
  const params = includeDeleted ? "?include_deleted=true" : "";
  return api.get<TodoItem[]>(`/todos${params}`);
}

export function createTodo(input: TodoInput) {
  return api.post<TodoItem>("/todos", input);
}

export function updateTodo(id: number, input: Partial<TodoInput>) {
  return api.patch<TodoItem>(`/todos/${id}`, input);
}

export function deleteTodo(id: number) {
  return api.delete<void>(`/todos/${id}`);
}

export function completeTodo(id: number) {
  return api.post<TodoItem>(`/todos/${id}/complete`, {});
}

export function stepTodo(id: number) {
  return api.post<TodoItem>(`/todos/${id}/step`, {});
}
