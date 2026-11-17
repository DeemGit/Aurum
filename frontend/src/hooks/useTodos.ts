import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  completeTodo,
  createTodo,
  deleteTodo,
  fetchTodos,
  stepTodo,
  updateTodo,
} from "@/api/todos";
import type { TodoInput } from "@/types";

function useInvalidateTodos() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["todos"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
  };
}

export function useTodos(includeDeleted: boolean) {
  return useQuery({
    queryKey: ["todos", includeDeleted],
    queryFn: () => fetchTodos(includeDeleted),
  });
}

export function useCreateTodo() {
  const invalidate = useInvalidateTodos();
  return useMutation({
    mutationFn: (input: TodoInput) => createTodo(input),
    onSuccess: invalidate,
  });
}

export function useUpdateTodo() {
  const invalidate = useInvalidateTodos();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: Partial<TodoInput> }) => updateTodo(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteTodo() {
  const invalidate = useInvalidateTodos();
  return useMutation({
    mutationFn: (id: number) => deleteTodo(id),
    onSuccess: invalidate,
  });
}

export function useCompleteTodo() {
  const invalidate = useInvalidateTodos();
  return useMutation({
    mutationFn: (id: number) => completeTodo(id),
    onSuccess: invalidate,
  });
}

export function useStepTodo() {
  const invalidate = useInvalidateTodos();
  return useMutation({
    mutationFn: (id: number) => stepTodo(id),
    onSuccess: invalidate,
  });
}
