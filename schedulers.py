import torch
import comfy.samplers
import comfy.model_sampling

class WanMoEScheduler:
    """
    A ComfyUI scheduler that finds the optimal sigma shift value.
    """
    
    DESCRIPTION = (
        "Finds an optimal sigma shift value and calculates sigmas for two-stage sampling.\n\n"
        "Note: The 'karras', 'exponential', 'linear_quadratic', 'kl_optimal', and 'bong_tangent' "
        "schedulers have been removed from the list because the 'shift' parameter has little to "
        "no effect on their sigma distributions."
    )

    @classmethod
    def INPUT_TYPES(cls):
        schedulers_to_remove = ["karras", "exponential", "linear_quadratic", "kl_optimal", "bong_tangent"]
        filtered_schedulers = [s for s in comfy.samplers.SCHEDULER_NAMES if s not in schedulers_to_remove]
        
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "The model used for calculating sigmas."
                }),
                "scheduler": (filtered_schedulers, {
                    "tooltip": "The scheduler to use for sigma calculation.\n\nNOTE: If you do not use sigmas for sampling don't forget to match the scheduler values."
                }),
                "steps_high": ("INT", {
                    "default": 4,
                    "min": 1,
                    "max": 99,
                    "tooltip": "Number of steps for high noise sampling."
                }),
                "steps_low": ("INT", {
                    "default": 4,
                    "min": 1,
                    "max": 99,
                    "tooltip": "Number of steps for the low noise sampling.\n\nNOTE: Higher steps require lower speed lora strength."
                }),
                "boundary": ("FLOAT", {
                    "default": 0.875,
                    "min": 0.0,
                    "max": 0.999,
                    "step": 0.001,
                    "round": 0.001,
                    "tooltip": "The target sigma value for the boundary between high and low steps. Usually 0.930-0.875.\n\nOffical WAN values are 0.90 (I2V) and 0.875 (T2V)."
                }),
                "interval": ("FLOAT", {
                    "default": 0.01,
                    "min": 0.01,
                    "max": 1.0,
                    "step": 0.01,
                    "round": 0.01,
                    "tooltip": "The step size to increment the shift while searching for the optimal value. Lower is more precise."
                }),
                "denoise": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "The amount of noise to remove. A value of 1.0 is full denoising (default)."
                }),
            }
        }

    RETURN_TYPES = ("FLOAT", "INT", "INT", "INT", "SIGMAS", "SIGMAS", "SIGMAS")
    RETURN_NAMES = ("shift", "steps", "steps_high", "steps_low", "sigmas", "sigmas_high", "sigmas_low")
    FUNCTION = "find_and_apply_shift"
    CATEGORY = "sampling/custom_sampling/schedulers"

    def find_and_apply_shift(self, model, scheduler, steps_high, steps_low, denoise, boundary, interval):
            
        steps_total = steps_high + steps_low
        calculation_steps = steps_total
        if denoise < 1.0:
            calculation_steps = int(steps_total / denoise)

        shift = 0.0
        max_shift = 100.0
        final_shift = 0.0
        found_sigmas = torch.zeros((steps_total + 1,))
        
        original_sampling = model.get_model_object("model_sampling")
        
        class ModelSamplingAdvanced(type(original_sampling)):
            pass
        
        try:
            while shift <= max_shift:
                try:
                    model_sampling = ModelSamplingAdvanced(model.model.model_config)
                    model_sampling.set_parameters(shift=shift)
                    model.add_object_patch("model_sampling", model_sampling)
                except Exception as e:
                    print(f"WanMoEScheduler: Could not patch model with shift {shift}. Error: {e}")
                    break

                sigmas = comfy.samplers.calculate_sigmas(model.get_model_object("model_sampling"), scheduler, calculation_steps).cpu()
                
                sigmas_denoised = sigmas[-(steps_total + 1):]

                if sigmas_denoised.shape[0] <= steps_high:
                    print(f"WanMoEScheduler: Not enough sigmas generated after denoising.")
                    break

                found_sigmas = sigmas_denoised
                final_shift = shift
                boundary_sigma = sigmas_denoised[steps_high]

                if boundary_sigma >= boundary:
                    break
                shift += interval
                assert shift <= max_shift, "Could not find shift."
                
        finally:
            model.add_object_patch("model_sampling", original_sampling)

        final_sigmas = found_sigmas[:steps_total + 1]
        sigmas_high = final_sigmas[:steps_high + 1]
        sigmas_low = final_sigmas[steps_high:]

        print(f"WanMoEScheduler shift: {round(final_shift, 2)}")
        print(f"WanMoEScheduler sigmas (high): {sigmas_high}")
        print(f"WanMoEScheduler sigmas (low): {sigmas_low}")

        return (round(final_shift, 2), steps_total, steps_high, steps_low, final_sigmas, sigmas_high, sigmas_low)